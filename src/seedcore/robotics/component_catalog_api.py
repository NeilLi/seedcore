"""Local, read-only Phase 1 catalog viewer; no admission or deployment routes."""

from __future__ import annotations

import copy
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .component_registry import (
    REGISTRY,
    ROOT,
    load_catalog,
    parse_json,
    read_local,
    sha256,
)


def create_app(registry: Path = REGISTRY):
    parts = load_catalog(registry)
    meshes = {}
    for part in parts:
        visual = part["mechanical"]["visual_mesh"]
        meshes[Path(visual["uri"]).name] = read_local(
            registry, visual["uri"], 1024 * 1024
        )
    reference = parse_json(read_local(registry, "references/microduck-0.1.0.json"))
    if reference["package_manifest"] != "packages/models/microduck/0.1.0/manifest.json":
        raise ValueError("unexpected native reference package")
    if (
        sha256(read_local(ROOT, reference["package_manifest"]))
        != reference["package_manifest_sha256"]
    ):
        raise ValueError("native Microduck package pin mismatch")
    snapshot = {
        "schema_version": "seedcore.catalog-view.v1",
        "scope": "authoring_only",
        "catalog_sha256": sha256(read_local(registry, "catalog.json")),
        "parts": parts,
        "reference": reference,
    }
    app = FastAPI(
        title="SeedCore component catalog (read-only)",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def local_headers(request: Request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "localhost viewer only"}, status_code=403)
        response = await call_next(request)
        for name, value in {
            "Cross-Origin-Opener-Policy": "same-origin",
            "Cross-Origin-Embedder-Policy": "require-corp",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        }.items():
            response.headers[name] = value
        return response

    @app.get("/api/catalog")
    def catalog():
        return copy.deepcopy(snapshot)

    @app.get("/assets/{name}")
    def asset(name: str):
        if name not in meshes:
            raise HTTPException(404, "asset is not in the frozen catalog")
        return Response(meshes[name], media_type="model/gltf-binary")

    @app.get("/{page:path}")
    def viewer(page: str):
        if page not in {"", "index.html", "viewer.js", "viewer.css"}:
            raise HTTPException(404, "viewer file not found")
        return FileResponse(REGISTRY / "viewer" / (page or "index.html"))

    return app
