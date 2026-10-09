# Versioned offline robot models

`model-package.schema.json` is generated from
`seedcore.robotics.model_package.ModelPackage.model_json_schema()`.
The Python contract additionally enforces unique inventories, valid paths,
parent-first body trees, and joint/actuator references. Validate with the loader,
not JSON Schema alone.

Each version directory contains a `manifest.json`, the model and all dependencies,
license text and source provenance. Packages are repository artifacts; they are
not bundled into the SeedCore Python wheel. Pass an explicit manifest path.

```bash
PYTHONPATH=src .venv/bin/python scripts/robotics/mujoco_workbench.py inspect-package \
  --manifest packages/models/microduck/0.1.0/manifest.json \
  --manifest-sha256 31018dfaa996b9a4ae519f121134b40331be2ef9b92835bb9274c5f777444371
```

See the [ingestion contract](../../docs/development/robotics/model_package_ingestion.md)
for the API, file limits and supported MJCF/URDF subset. Treat published versions
as immutable: changes to model bytes or parity expectations require a new version
and a reviewed manifest pin.
