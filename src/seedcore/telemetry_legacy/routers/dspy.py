from fastapi import APIRouter
router = APIRouter()

# TODO: Move these handlers from telemetry/server.py into this module,
# converting '@app.METHOD("/prefix/..")' to '@router.METHOD("/..")'.
# - POST /dspy/reason-about-failure -> def reason_about_failure(...)
# - POST /dspy/plan-task -> def plan_task(...)
# - POST /dspy/make-decision -> def make_decision(...)
# - POST /dspy/solve-problem -> def solve_problem(...)
# - POST /dspy/synthesize-memory -> def synthesize_memory(...)
# - POST /dspy/assess-capabilities -> def assess_capabilities(...)
# - GET /dspy/status -> def get_dspy_status(...)
