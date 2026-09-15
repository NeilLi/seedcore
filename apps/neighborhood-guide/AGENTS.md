# Neighborhood Guide contributor rules

This is an isolated, presentation-only Godot application for testing a
curated neighborhood journey. It is not part of SeedCore's policy decision,
execution-token, custody, or evidence-closure paths.

- Keep scenes, scripts, resources, and source assets reviewable in Git.
- Store source Blender files in `assets/blender/`; export reviewed `.glb`
  artifacts to `assets/models/`.
- Use meters: one Blender/Godot unit equals one meter. Keep street modules on
  the 2 m grid unless a reviewed landmark needs an exception.
- `*-col` meshes are collision proxies only. Do not turn presentation geometry,
  camera positions, route suggestions, or POI tags into evidence or execution
  authority.
- Add POIs as `POIResource` instances attached to `POIAnchor3D` nodes. Keep
  source, consent, and freshness details in the ordinary discovery system; this
  prototype uses fictional placeholder copy only.
- Preserve the “prompt → curated walk → discovery” loop. A route is advisory
  and must never cause a booking, payment, custody action, or external write.
- Run `tools/check_environment.sh` and `tools/validate_project.sh` after
  changing project configuration, scenes, or scripts. When a deterministic
  check keeps failing, stop and leave the output plus reproduction steps for
  review.
