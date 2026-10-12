"""Bounded local concurrency configuration shared by task and stage admission."""
import os

LANES = ("heavy", "light", "download")
LIGHT_TASK_KINDS = {"light", "summary", "local_light", "page_light"}
LANE_PENDING_LIMIT = 12


class QueueFull(ValueError):
    pass


def task_lane(kind: str) -> str:
    if kind == "page_download":
        return "download"
    return "light" if kind in LIGHT_TASK_KINDS else "heavy"


def lane_budgets() -> dict[str, int]:
    budgets = {}
    low_resource = os.getenv("LEARNNOTE_LOW_RESOURCE_MODE", "").lower() in {"1", "true", "yes"}
    for lane in LANES:
        try:
            count = int(os.getenv(f"LEARNNOTE_{lane.upper()}_CONCURRENCY", "1"))
        except ValueError:
            raise ValueError("Queue concurrency must be an integer from 1 through 4") from None
        if not 1 <= count <= 4:
            raise ValueError("Queue concurrency must be an integer from 1 through 4")
        budgets[lane] = 1 if low_resource else count
    return budgets
