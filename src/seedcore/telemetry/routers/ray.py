from fastapi import APIRouter
router = APIRouter()

# TODO: Move these handlers from telemetry/server.py into this module,
# converting '@app.METHOD("/prefix/..")' to '@router.METHOD("/..")'.
# - GET /ray/status -> def get_ray_status(...)
# - POST /ray/connect -> def connect_ray(...)
