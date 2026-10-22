"""Local CW-A02 authoring service. Validation never grants runtime admission."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from jsonschema import ValidationError

from .assembly import (
    compute_assembly_digest, compute_node_world_transforms, load_assembly_catalog, validate_assembly,
)
from .component_registry import REGISTRY, ROOT, parse_json, read_local, sha256

MAX_BODY = 262144


def create_app(registry: Path = REGISTRY, web_root: Path | None = None):
    catalog = load_assembly_catalog(registry)
    documents = {parse_json(raw)["identity"]["part_id"]: raw for raw in catalog.artifacts}
    meshes = {}
    for raw in catalog.artifacts:
        visual = parse_json(raw)["mechanical"]["visual_mesh"]
        data = read_local(registry, visual["uri"], 1024 * 1024)
        if sha256(data) != visual["sha256"]:
            raise ValueError("mesh changed during startup")
        meshes[Path(visual["uri"]).name] = data
    starter = read_local(registry, "assemblies/tabletop-starter.sc-assembly.json", MAX_BODY)
    validate_assembly(parse_json(starter), catalog, root=registry)
    catalog_raw = read_local(registry, "catalog.json")
    catalog_sha = sha256(catalog_raw)
    web_root = web_root or ROOT / "ts/apps/mini-studio/dist"
    scene_root = ROOT / "packages/scene-fixtures/mini-workbench"
    scene_assets = {name: read_local(scene_root, name, 1048576) for name in
                    ["scene.json", "tileset.json", "coarse.glb", *[f"detail-{i}.glb" for i in range(4)]]}
    app = FastAPI(title="SeedCore offline Mini Studio", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "localhost authoring only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "same-origin authoring only"}, status_code=403)
        response = await call_next(request)
        # Only the opt-in simulation labs and physics worker may compile pinned Wasm.
        # The editor retains its existing no-eval policy; no arbitrary JS eval.
        scene_policy = request.url.path in {"/scene.html", "/scene-worker.js"}
        wasm_policy = " 'wasm-unsafe-eval'" if scene_policy or request.url.path in {"/performance.html", "/lab-physics.js"} else ""
        blob_policy = " blob:" if scene_policy else ""
        response.headers.update({
            "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Embedder-Policy": "require-corp",
            "Cross-Origin-Resource-Policy": "same-origin", "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": f"default-src 'self'; script-src 'self'{wasm_policy}; worker-src 'self'{blob_policy}; style-src 'self'; connect-src 'self'{blob_policy}; img-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        })
        return response

    @app.get("/api/starter")
    def get_starter():
        return Response(starter, media_type="application/json")

    @app.get("/api/placement-catalog")
    def placement_catalog():
        return {
            "scope": "offline_proxy_authoring", "physical_acceptance": False,
            "catalog_sha256": catalog_sha, "catalog_raw_json": catalog_raw.decode("utf-8"),
            "part_documents": [{"part_id": key, "raw_json": raw.decode("utf-8")} for key, raw in sorted(documents.items())],
        }

    @app.post("/api/assembly/validate")
    async def validate(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(415, "application/json required")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                raise HTTPException(413, "assembly exceeds 262144 bytes")
        try:
            assembly = validate_assembly(parse_json(bytes(body)), catalog, root=registry)
        except (ValueError, ValidationError, UnicodeError, RecursionError) as error:
            detail = error.message if isinstance(error, ValidationError) else str(error)
            raise HTTPException(422, detail[:500]) from error
        ids = sorted({node["part_id"] for node in assembly["nodes"]})
        return {
            "scope": "offline_proxy_authoring", "physical_acceptance": False,
            "assembly_digest": compute_assembly_digest(assembly), "catalog_sha256": catalog_sha,
            "part_documents": [{"part_id": key, "raw_json": documents[key].decode("utf-8")} for key in ids],
            "transforms": compute_node_world_transforms(assembly),
        }

    @app.get("/assets/{name}")
    def asset(name: str):
        if name not in meshes:
            raise HTTPException(404, "asset outside frozen catalog")
        return Response(meshes[name], media_type="model/gltf-binary")

    @app.get("/scene-assets/{name}")
    def scene_asset(name: str):
        if name not in scene_assets:
            raise HTTPException(404, "asset outside synthetic static fixture")
        return Response(scene_assets[name], media_type="model/gltf-binary" if name.endswith(".glb") else "application/json")

    @app.get("/{page:path}")
    def page(page: str):
        name = page or "index.html"
        if name not in {"index.html", "app.js", "app.css", "third-party-notices.txt", "favicon.svg",
                        "performance.html", "performance.js", "performance.css", "lab-physics.js", "lab-render.js", "lab-physics.wasm",
                        "scene.html", "scene.css", "scene.js", "scene-worker.js", "scene-build.json",
                        "scene-decoders/draco_decoder.wasm", "scene-decoders/draco_wasm_wrapper.js"} or not (web_root / name).is_file():
            raise HTTPException(404, "build Mini Studio before serving")
        return FileResponse(web_root / name, media_type="application/wasm" if name.endswith(".wasm") else None)

    return app
