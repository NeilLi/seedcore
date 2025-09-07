from fastapi import APIRouter
router = APIRouter()

# TODO: Move these handlers from telemetry/server.py into this module,
# converting '@app.METHOD("/prefix/..")' to '@router.METHOD("/..")'.
# - POST /{organ_id}/set -> def mw_set_item(...)
# - GET /{organ_id}/get/{item_id} -> def mw_get_item(...)
