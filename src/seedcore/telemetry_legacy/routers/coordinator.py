from fastapi import APIRouter
router = APIRouter()

# TODO: Move these handlers from telemetry/server.py into this module,
# converting '@app.METHOD("/prefix/..")' to '@router.METHOD("/..")'.
# - GET /coordinator/health -> def get_coordinator_health(...)
# - POST /coordinator/submit -> def submit_coordinator(...)
