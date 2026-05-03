"""
Account tools — used by AccountAgent.

These tools query the DB for user-specific data.
Mock data is used for the take-home; the wiring is evaluated.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class BuildSummary:
    build_id: str
    pipeline: str
    status: str  # passed | failed | cancelled
    branch: str
    started_at: datetime
    duration_seconds: int


@dataclass
class AccountStatus:
    user_id: str
    plan_tier: str
    concurrent_builds_used: int
    concurrent_builds_limit: int
    storage_used_gb: float
    storage_limit_gb: float


# Mock data for demonstration
MOCK_BUILDS = {
    "u_test_001": [
        BuildSummary(
            build_id="build_001",
            pipeline="main",
            status="passed",
            branch="main",
            started_at=datetime.utcnow() - timedelta(hours=2),
            duration_seconds=180,
        ),
        BuildSummary(
            build_id="build_002",
            pipeline="release",
            status="failed",
            branch="release/v1.2.0",
            started_at=datetime.utcnow() - timedelta(hours=5),
            duration_seconds=420,
        ),
        BuildSummary(
            build_id="build_003",
            pipeline="main",
            status="passed",
            branch="main",
            started_at=datetime.utcnow() - timedelta(hours=8),
            duration_seconds=165,
        ),
    ],
    "u_test_002": [
        BuildSummary(
            build_id="build_004",
            pipeline="pr-check",
            status="passed",
            branch="feature/new-api",
            started_at=datetime.utcnow() - timedelta(hours=1),
            duration_seconds=240,
        ),
    ],
}

MOCK_ACCOUNT_STATUS = {
    "u_test_001": AccountStatus(
        user_id="u_test_001",
        plan_tier="pro",
        concurrent_builds_used=2,
        concurrent_builds_limit=5,
        storage_used_gb=45.2,
        storage_limit_gb=100.0,
    ),
    "u_test_002": AccountStatus(
        user_id="u_test_002",
        plan_tier="enterprise",
        concurrent_builds_used=8,
        concurrent_builds_limit=20,
        storage_used_gb=256.7,
        storage_limit_gb=1000.0,
    ),
}


async def get_recent_builds(user_id: str, limit: int = 5) -> dict:
    """
    Return the most recent builds for a user, newest first.

    For the take-home: returning mock/seeded data is acceptable.
    The key evaluation point is that this is wired as an ADK tool
    and the agent correctly invokes it when the user asks about builds.

    Returns a dict with 'builds' key containing list of build records.
    """
    builds_list = MOCK_BUILDS.get(user_id, [])
    builds_to_return = builds_list[:limit]

    return {
        "builds": [
            {
                "build_id": b.build_id,
                "pipeline": b.pipeline,
                "status": b.status,
                "branch": b.branch,
                "started_at": b.started_at.isoformat(),
                "duration_seconds": b.duration_seconds,
            }
            for b in builds_to_return
        ]
    }


async def get_account_status(user_id: str) -> dict:
    """
    Return current account status (plan, usage limits).

    For the take-home: mock data is acceptable.
    Returns a dict with account information or error message.
    """
    status = MOCK_ACCOUNT_STATUS.get(user_id)
    if not status:
        return {"error": f"Account not found for user {user_id}"}

    return {
        "user_id": status.user_id,
        "plan_tier": status.plan_tier,
        "concurrent_builds_used": status.concurrent_builds_used,
        "concurrent_builds_limit": status.concurrent_builds_limit,
        "storage_used_gb": status.storage_used_gb,
        "storage_limit_gb": status.storage_limit_gb,
    }
