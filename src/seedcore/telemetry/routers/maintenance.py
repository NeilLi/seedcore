from fastapi import APIRouter
router = APIRouter()

# TODO: Move these handlers from telemetry/server.py into this module,
# converting '@app.METHOD("/prefix/..")' to '@router.METHOD("/..")'.
# - GET /maintenance/status -> def get_maintenance_status(...)
# - POST /maintenance/cleanup -> def cleanup_maintenance(...)
# - GET /maintenance/dead-actors -> def get_dead_actors(...)
