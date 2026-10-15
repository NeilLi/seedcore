"""Bounded host-side controller simulation with an independent watchdog.

The only sink is an in-process mathematical joint state. No actuator injection,
serial port, native Microduck RPC or device enable path exists in this profile.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import math
import hashlib
from pathlib import Path
from threading import Event, RLock, Thread
import time

from .authority import TokenAuthority
from .contracts import (
    CommandChunk,
    ControlMessage,
    MAX_EVENTS,
    MAX_SEQUENCE,
    SessionOpen,
    SessionSpec,
    digest,
)
from .protocol import MessageType, decode_frame
from .store import ClaimStore


class SessionRuntime:
    def __init__(
        self,
        spec: SessionSpec,
        authority: TokenAuthority,
        store: ClaimStore,
        *,
        channel_key: bytes,
        clock=time.monotonic,
        wall_clock=lambda: datetime.now(timezone.utc),
        authority_source=None,
    ):
        self.spec = SessionSpec.model_validate(spec.model_dump(mode="json"))
        if not isinstance(channel_key, bytes) or len(channel_key) != 32:
            raise ValueError("provisioned channel key required")
        self._authority, self._store, self._key = authority, store, channel_key
        self._clock, self._wall = clock, wall_clock
        self._source = authority_source
        self._lock = RLock()
        self._shutdown = Event()
        self._thread = None
        self._state = "created"
        self._reason = None
        self._claims = None
        self._positions = tuple(self.spec.initial_rad)
        self._points = []  # (relative_ms, positions, command_sequence)
        self._events = []
        self._capture_complete = True
        self._sequence = 0
        self._last_clock = self._clock()
        self._started = self._last_clock
        self._last_command = self._last_heartbeat = self._started
        self._deadline = self._started
        self._submitted = False
        self._runtime_sha256 = hashlib.sha256(
            b"".join(
                p.name.encode("ascii") + b"\x00" + p.read_bytes()
                for p in sorted(Path(__file__).parent.glob("*.py"))
            )
        ).hexdigest()

    def _elapsed(self, now):
        return max(0, int((now - self._started) * 1000 + 1e-6))

    def _event(self, kind, now, **detail):
        if len(self._events) >= MAX_EVENTS - 1 and kind != "closed":
            self._capture_complete = False
            return False
        self._events.append(
            {
                "sequence": len(self._events),
                "t_ms": self._elapsed(now),
                "kind": kind,
                "positions_urad": [round(q * 1_000_000) for q in self._positions],
                **detail,
            }
        )
        return True

    def _fence(self, reason, now):
        if self._state == "active":
            self._state, self._reason = "fenced", reason
            self._points.clear()
            self._event("closed", max(now, self._last_clock), reason=reason)

    def admit(self, token: dict):
        with self._lock:
            if self._state != "created":
                raise PermissionError("session already admitted/fenced")
            now = self._clock()
            if not math.isfinite(now) or now < self._last_clock:
                raise PermissionError("invalid/rolled-back monotonic clock")
            wall = self._wall()
            claims = self._authority.verify(copy.deepcopy(token), self.spec, now=wall)
            # The durable claim is never released, including after interruption.
            self._store.claim(
                token_id=claims["token_id"],
                token_hash=claims["token_sha256"],
                endpoint=self.spec.endpoint_id,
                session_id=self.spec.session_id,
                key_ref=claims["key_ref"],
            )
            self._claims = claims
            self._started = self._last_clock = now
            self._last_command = self._last_heartbeat = now
            self._deadline = min(
                now + self.spec.duration_ms / 1000,
                now + (claims["expires"] - wall).total_seconds(),
            )
            self._points = [(0, self._positions, 0)]
            self._state = "active"
            self._event("opened", now)
            self.poll()  # Account for verification/claim latency before any command.
            if self._state != "active":
                raise PermissionError("admission expired or authority unavailable")
            return self.status()

    def _check(self, now):
        if not math.isfinite(now) or now < self._last_clock:
            self._fence("clock_rollback", self._last_clock)
            return False
        self._last_clock = now
        if now >= self._deadline or self._wall() >= self._claims["expires"]:
            self._fence("session_deadline", now)
            return False
        try:
            if self._source:
                revoked, observed = self._source(
                    self._claims["token_id"], self._claims["key_ref"]
                )
            else:
                revoked = self._store.is_revoked(
                    self._claims["token_id"], self._claims["key_ref"]
                )
                observed = now
            if revoked:
                self._fence("revoked", now)
                return False
            if (
                not math.isfinite(observed)
                or not 0 <= now - observed <= self.spec.authority_timeout_ms / 1000
            ):
                self._fence("stale_authority", now)
                return False
        except Exception:
            self._fence("authority_unavailable", now)
            return False
        if now - self._last_command >= self.spec.command_timeout_ms / 1000:
            self._fence("stale_command", now)
            return False
        if now - self._last_heartbeat >= self.spec.heartbeat_timeout_ms / 1000:
            self._fence("lost_heartbeat", now)
            return False
        return True

    def poll(self):
        with self._lock:
            if self._state != "active":
                return
            now = self._clock()
            if not self._check(now):
                return
            elapsed = self._elapsed(now)
            while len(self._points) > 1 and elapsed >= self._points[1][0]:
                self._points.pop(0)
                _, self._positions, seq = self._points[0]
                if not self._event("applied", now, command_sequence=seq):
                    self._fence("capture_overflow", now)
                    return
            if len(self._points) > 1:
                begin, before, _ = self._points[0]
                end, after, _ = self._points[1]
                u = max(0.0, min(1.0, (elapsed - begin) / (end - begin)))
                weight = u**3 * (10 - 15 * u + 6 * u**2)
                self._positions = tuple(
                    a + weight * (b - a) for a, b in zip(before, after, strict=True)
                )
            if not self._event("sample", now):
                self._fence("capture_overflow", now)

    def _binding(self, message):
        if self._state != "active":
            raise PermissionError("session is not active; fresh admission required")
        if (
            message.session_id,
            message.endpoint_id,
            message.boot_nonce,
            message.token_sha256,
        ) != (
            self.spec.session_id,
            self.spec.endpoint_id,
            self.spec.boot_nonce,
            self._claims["token_sha256"],
        ):
            raise PermissionError("session/endpoint/boot/token binding mismatch")
        if self._sequence == MAX_SEQUENCE or message.sequence != self._sequence + 1:
            raise PermissionError("replayed/out-of-order/exhausted command sequence")

    def submit(self, chunk: CommandChunk):
        with self._lock:
            chunk = CommandChunk.model_validate(chunk.model_dump(mode="json"))
            self.poll()
            self._binding(chunk)
            now = self._clock()
            elapsed = self._elapsed(now)
            if not 0 <= elapsed - chunk.generated_at_ms < self.spec.command_timeout_ms:
                raise PermissionError("stale/future command")
            points = list(self._points)
            if len(points) == 1:
                points = [(elapsed, self._positions, self._sequence)]
            if len(points) + len(chunk.waypoints) > 64:
                raise PermissionError("motion buffer full")
            previous_ms, previous_q, _ = points[-1]
            for point in chunk.waypoints:
                q, at = point.positions_rad, point.at_ms
                if (
                    len(q) != len(self._positions)
                    or not previous_ms < at < self.spec.duration_ms
                ):
                    raise PermissionError("joint dimensions or waypoint time invalid")
                if self._started + at / 1000 >= self._deadline:
                    raise PermissionError("chunk exceeds admitted deadline")
                if any(
                    not lo <= target <= hi
                    for lo, target, hi in zip(
                        self.spec.lower_rad, q, self.spec.upper_rad, strict=True
                    )
                ):
                    raise PermissionError("waypoint outside admitted joint envelope")
                # Exact extrema for zero-end-velocity/acceleration quintic smoothstep.
                duration = (at - previous_ms) / 1000
                distance = max(abs(a - b) for a, b in zip(previous_q, q, strict=True))
                if (
                    1.875 * distance / duration > self.spec.max_velocity_rad_s
                    or (10 / math.sqrt(3)) * distance / duration**2
                    > self.spec.max_acceleration_rad_s2
                    or 60 * distance / duration**3 > self.spec.max_jerk_rad_s3
                ):
                    raise PermissionError(
                        "spline velocity/acceleration/jerk limit exceeded"
                    )
                points.append((at, tuple(q), chunk.sequence))
                previous_ms, previous_q = at, q
            # Commit only after validation of the entire chunk.
            chunk_sha256 = digest(chunk.model_dump(mode="json"))
            now = self._clock()
            if not self._check(now):
                raise PermissionError("authority expired during command validation")
            elapsed = self._elapsed(now)
            if (
                elapsed - chunk.generated_at_ms >= self.spec.command_timeout_ms
                or chunk.waypoints[0].at_ms <= elapsed
            ):
                raise PermissionError("command expired during validation")
            if not self._event(
                "queued",
                now,
                command_sequence=chunk.sequence,
                chunk_sha256=chunk_sha256,
            ):
                self._fence("capture_overflow", now)
                raise PermissionError("capture buffer unavailable")
            self._points = points
            self._sequence, self._last_command = chunk.sequence, now
            self._submitted = True
            return {"status": "queued", "sequence": self._sequence, "physical": False}

    def control(self, message: ControlMessage, kind: MessageType):
        with self._lock:
            message = ControlMessage.model_validate(message.model_dump(mode="json"))
            self.poll()
            self._binding(message)
            now = self._clock()
            if kind == MessageType.HEARTBEAT:
                self._last_heartbeat = now  # Never refreshes command age or deadline.
                self._event("heartbeat", now, command_sequence=message.sequence)
            elif kind in {MessageType.CANCEL, MessageType.REVOKE}:
                if kind == MessageType.REVOKE:
                    self._store.revoke(self._claims["token_id"])
                self._fence(
                    "revoked" if kind == MessageType.REVOKE else "cancelled", now
                )
            elif kind == MessageType.SESSION_END:
                if not self._submitted or len(self._points) != 1:
                    raise PermissionError("queued motion has not completed")
                self._fence("completed", now)
            else:
                raise PermissionError("unsupported control operation")
            self._sequence = message.sequence
            if len(self._events) >= MAX_EVENTS - 1 and self._state == "active":
                self._capture_complete = False
                self._fence("capture_overflow", now)

    def accept_frame(self, frame: bytes):
        kind, sequence, payload = decode_frame(frame, self._key)
        if kind == MessageType.HELLO:
            if sequence != 0 or payload != {"profile": "simulation_only"}:
                raise PermissionError("invalid discovery request")
            return {
                "profile": "simulation_only",
                "physical": False,
                "protocol_version": 1,
                "endpoint_id": self.spec.endpoint_id,
                "boot_nonce": self.spec.boot_nonce,
            }
        if kind == MessageType.SESSION_OPEN:
            message = SessionOpen.model_validate(payload)
            if sequence != 0 or message.spec.sha256 != self.spec.sha256:
                raise PermissionError("session-open profile binding mismatch")
            return self.admit(message.execution_token)
        if kind == MessageType.CHUNK:
            message = CommandChunk.model_validate(payload)
            if message.sequence != sequence:
                raise PermissionError("header/payload sequence mismatch")
            return self.submit(message)
        message = ControlMessage.model_validate(payload)
        if message.sequence != sequence:
            raise PermissionError("header/payload sequence mismatch")
        return self.control(message, kind)

    def local_stop(self):
        with self._lock:
            try:
                now = self._clock()
                if not math.isfinite(now):
                    raise ValueError("invalid stop clock")
            except Exception:
                # Clock failure cannot prevent the local fence. The missing
                # trustworthy capture time prevents a complete evidence claim.
                now = self._last_clock
                self._capture_complete = False
            self._fence("local_stop", now)

    def status(self):
        with self._lock:
            return {
                "profile": "simulation_only",
                "physical": False,
                "state": self._state,
                "reason": self._reason,
                "sequence": self._sequence,
                "positions_rad": list(self._positions),
                "queued_points": max(0, len(self._points) - 1),
                "deadline_monotonic": self._deadline,
                "capture_complete": self._capture_complete,
            }

    def receipt_payload(self):
        with self._lock:
            if self._state != "fenced":
                raise RuntimeError("active session cannot be sealed as complete")
            return {
                "schema_version": "seedcore.fast-spine.receipt.v1",
                "profile": "simulation_only",
                "capture_kind": "simulated_controller_state",
                "session_id": self.spec.session_id,
                "endpoint_id": self.spec.endpoint_id,
                "boot_nonce": self.spec.boot_nonce,
                "principal_id": self.spec.principal_id,
                "policy_sha256": self.spec.policy_sha256,
                "model_sha256": self.spec.model_sha256,
                "runtime_sha256": self._runtime_sha256,
                "spec_sha256": self.spec.sha256,
                "token_id": self._claims["token_id"],
                "intent_id": self._claims["intent_id"],
                "token_sha256": self._claims["token_sha256"],
                "outcome": self._reason,
                "capture_complete": self._capture_complete,
                "events": copy.deepcopy(self._events),
            }

    def start_watchdog(self):
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("watchdog already started")

            def run():
                while not self._shutdown.wait(0.005):
                    try:
                        self.poll()
                    except Exception:
                        with self._lock:
                            self._fence("watchdog_fault", self._last_clock)

            self._thread = Thread(
                target=run, name="seedcore-spine-sim-watchdog", daemon=True
            )
            self._thread.start()

    def close(self):
        self.local_stop()
        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
