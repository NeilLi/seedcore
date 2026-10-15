"""Localhost-only simulation fixture service; never a production action gateway."""

from __future__ import annotations

import copy
from pathlib import Path
import secrets
from threading import RLock
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from typing import Literal

from seedcore.integrations.rust_kernel import verify_spine_session_with_rust
from .authority import TokenAuthority
from .contracts import CommandChunk, ControlMessage, digest
from .evidence import seal_receipt, simulation_trust_bundle, verify_receipt
from .protocol import MessageType, encode_frame
from .rehearsal import fixture_spec, fixture_token
from .session import SessionRuntime
from .store import ClaimStore

ROOT = Path(__file__).resolve().parents[4]


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case: Literal["allowed", "out_of_bounds", "expired", "forged", "wrong_endpoint"] = (
        "allowed"
    )
    joints: Literal[1, 3] = 3


class Studio:
    def __init__(self, state_dir: Path):
        state_dir.mkdir(parents=True, exist_ok=True)
        self.store = ClaimStore(state_dir / "claims.sqlite")
        self.issuer = Ed25519PrivateKey.generate()
        self.signer = Ed25519PrivateKey.generate()
        self.authority = TokenAuthority(
            {"simulation-fixture-pdp": self.issuer.public_key()}
        )
        self.key = secrets.token_bytes(32)
        self.runtime = None
        self.token = None
        self.spec = None
        self.sealed = None
        self.result = None
        self.decision = {"status": "ready", "reason": "Choose an experiment."}
        self.lock = RLock()
        self.started = 0.0
        self.goal = 0.0
        self.last_refresh_ms = -1000

    def start(self, request: StartRequest):
        with self.lock:
            if self.runtime:
                self.runtime.close()
            self.runtime = self.token = self.spec = self.sealed = self.result = None
            spec = fixture_spec(request.joints)
            if request.case == "out_of_bounds":
                self.decision = {
                    "status": "denied",
                    "reason": "Proposed target exceeds the permitted joint envelope.",
                    "dispatched_commands": 0,
                }
                return self.status()
            token = fixture_token(spec, self.issuer)
            if request.case == "expired":
                from datetime import datetime, timedelta, timezone

                token = fixture_token(
                    spec,
                    self.issuer,
                    now=datetime.now(timezone.utc) - timedelta(seconds=2),
                )
            elif request.case == "forged":
                token["constraints"]["payload_hash"] = "0" * 64
            elif request.case == "wrong_endpoint":
                token = fixture_token(
                    spec.model_copy(update={"endpoint_id": "spine_sim://other"}),
                    self.issuer,
                )
            runtime = SessionRuntime(
                spec, self.authority, self.store, channel_key=self.key
            )
            try:
                runtime.accept_frame(
                    encode_frame(
                        MessageType.SESSION_OPEN,
                        0,
                        {
                            "spec": spec.model_dump(mode="json"),
                            "execution_token": token,
                        },
                        self.key,
                    )
                )
            except (ValueError, PermissionError, RuntimeError) as exc:
                runtime.close()
                self.decision = {
                    "status": "denied",
                    "reason": str(exc),
                    "dispatched_commands": 0,
                }
                return self.status()
            self.runtime, self.token, self.spec = runtime, token, spec
            self.started = time.monotonic()
            self.goal = 0.0
            self.last_refresh_ms = -1000
            self.decision = {
                "status": "allowed",
                "reason": "A bounded simulation session was admitted.",
                "dispatched_commands": 0,
            }
            self.refresh()
            runtime.start_watchdog()
            return self.status()

    def refresh(self):
        with self.lock:
            if not self.runtime or self.runtime.status()["state"] != "active":
                raise PermissionError("no active simulation session")
            elapsed = int((time.monotonic() - self.started) * 1000)
            if elapsed >= 850 or elapsed - self.last_refresh_ms < 80:
                return self.status()  # No extension past the admitted one-second lease.
            # Browser intervals may fire immediately after admission. Keep the
            # fixed lesson's adjacent waypoint intervals long enough for its
            # jerk bound; an early HTTP refresh grants no new command or lease.
            # Only this fixed, bounded lesson target is available to the browser.
            self.goal = min(0.02, self.goal + 0.002)
            seq = self.runtime.status()["sequence"] + 1
            chunk = CommandChunk(
                session_id=self.spec.session_id,
                endpoint_id=self.spec.endpoint_id,
                boot_nonce=self.spec.boot_nonce,
                token_sha256=digest(self.token),
                sequence=seq,
                generated_at_ms=elapsed,
                waypoints=(
                    {
                        "at_ms": min(950, elapsed + 100),
                        "positions_rad": [self.goal] * len(self.spec.initial_rad),
                    },
                ),
            )
            self.runtime.accept_frame(
                encode_frame(
                    MessageType.CHUNK, seq, chunk.model_dump(mode="json"), self.key
                )
            )
            seq += 1
            control = ControlMessage(
                session_id=self.spec.session_id,
                endpoint_id=self.spec.endpoint_id,
                boot_nonce=self.spec.boot_nonce,
                token_sha256=digest(self.token),
                sequence=seq,
            )
            self.runtime.accept_frame(
                encode_frame(
                    MessageType.HEARTBEAT,
                    seq,
                    control.model_dump(mode="json"),
                    self.key,
                )
            )
            self.last_refresh_ms = elapsed
            self.decision["dispatched_commands"] += 1
            return self.status()

    def stop(self, kind):
        with self.lock:
            if self.runtime:
                if kind == "revoke":
                    self.store.revoke(self.token["token_id"])
                    self.runtime.poll()
                else:
                    self.runtime.local_stop()
            return self.status()

    def status(self):
        with self.lock:
            result = {
                "profile": "simulation_only",
                "physical": False,
                "decision": copy.deepcopy(self.decision),
            }
            if self.runtime:
                state = self.runtime.status()
                result.update(
                    session=state,
                    target_rad=self.goal,
                    joints=len(self.spec.initial_rad),
                    session_id=self.spec.session_id,
                    token_id=self.token["token_id"],
                )
                if state["state"] == "fenced" and self.sealed is None:
                    self.sealed = seal_receipt(
                        self.runtime.receipt_payload(), self.signer
                    )
                    self.result = verify_receipt(
                        self.sealed,
                        {"simulation-receipt-host": self.signer.public_key()},
                        spec=self.spec,
                        token_sha256=digest(self.token),
                    )
                result["verification"] = copy.deepcopy(self.result)
            return result

    def evidence(self):
        with self.lock:
            self.status()
            if not self.sealed:
                raise PermissionError("stop the attempt before exporting evidence")
            bundle = simulation_trust_bundle(
                {"simulation-receipt-host": self.signer.public_key()},
                endpoint_id=self.spec.endpoint_id,
            )
            rust = verify_spine_session_with_rust(
                self.sealed,
                spec=self.spec.model_dump(mode="json"),
                trust_bundle=bundle,
                token_sha256=digest(self.token),
            )
            return {
                "receipt": copy.deepcopy(self.sealed),
                "spec": self.spec.model_dump(mode="json"),
                "token_sha256": digest(self.token),
                "trust_bundle": bundle,
                "python_verification": copy.deepcopy(self.result),
                "rust_verification": rust,
            }

    def close(self):
        if self.runtime:
            self.runtime.close()
        self.store.close()


def create_app(state_dir: Path):
    from contextlib import asynccontextmanager

    studio = Studio(state_dir)

    @asynccontextmanager
    async def lifespan(app):
        yield
        studio.close()

    app = FastAPI(title="SeedCore simulation rehearsal", lifespan=lifespan)
    app.state.studio = studio

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        from fastapi.responses import JSONResponse

        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "localhost rehearsal only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") != str(request.base_url).rstrip(
            "/"
        ):
            return JSONResponse(
                {"detail": "cross-origin simulation control rejected"}, status_code=403
            )
        return await call_next(request)

    @app.get("/")
    def root():
        return RedirectResponse("/studio/session-lab.html")

    @app.get("/api/spine-demo/state")
    def state():
        return studio.status()

    @app.post("/api/spine-demo/start")
    def start(body: StartRequest):
        return studio.start(body)

    @app.post("/api/spine-demo/refresh")
    def refresh():
        try:
            return studio.refresh()
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/spine-demo/{operation}")
    def stop(operation: Literal["stop", "revoke"]):
        return studio.stop(operation)

    @app.get("/api/spine-demo/evidence")
    def evidence():
        try:
            return studio.evidence()
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc

    app.mount(
        "/studio",
        StaticFiles(directory=ROOT / "apps/mini-robot-simulator", html=True),
        name="studio",
    )
    return app
