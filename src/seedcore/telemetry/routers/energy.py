from fastapi import APIRouter
router = APIRouter()

# TODO: Move these handlers from telemetry/server.py into this module,
# converting '@app.METHOD("/prefix/..")' to '@router.METHOD("/..")'.
# - GET /meta -> def energy_meta(...)
# - GET /calibrate -> def energy_calibrate(...)
# - GET /health -> def energy_health(...)
# - GET /monitor -> def energy_monitor(...)
# - GET /pair_stats -> def energy_pair_stats(...)
# - POST /log -> def energy_log(...)
# - GET /logs -> def energy_logs(...)
# - GET /gradient -> def energy_gradient(...)
