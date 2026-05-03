"""
AccountAgent — specialist for user account and usage questions.

Provides tools to query account status, build history, and usage metrics.
"""
from google.adk.agents import LlmAgent

from app.agents.tools.account_tools import get_recent_builds, get_account_status
from app.settings import settings

ACCOUNT_INSTRUCTION = """
You are the Helix Account Agent — a specialist for user account and usage questions.

When the user asks about:
- Their recent builds or pipelines → use get_recent_builds
- Their account status, plan, or usage limits → use get_account_status

Always be friendly and provide clear summaries. Include specific numbers and status info.

Example response:
"You have 2 concurrent builds active out of a limit of 5. Your last build (build_001) passed in 3 minutes."
"""

account_agent = LlmAgent(
    name="account",
    model=settings.adk_model,
    instruction=ACCOUNT_INSTRUCTION,
    tools=[get_recent_builds, get_account_status],  # ADK inspects function signatures
)
