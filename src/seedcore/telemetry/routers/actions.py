from fastapi import APIRouter
router = APIRouter()

# TODO: Move these handlers from telemetry/server.py into this module,
# converting '@app.METHOD("/prefix/..")' to '@router.METHOD("/..")'.
# - POST /run_two_agent_task -> def run_two_agent_task(...)
# - POST /run_slow_loop -> def run_slow_loop_endpoint(...)
# - POST /reset -> def reset_simulation(...)
