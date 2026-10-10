"""Explicit, short-lived conversational context; the archive is not a prompt."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def conversation_turns(items: list[dict], conversation_id: str, skill_id: str,
                       *, now: datetime | None = None) -> list[dict]:
    """Use only this live conversation's contiguous, successful recent turns.

    Legacy clients without a conversation id remain stateless. Archived help,
    another browser/source, and old sessions can never silently enter chat.
    """
    if not conversation_id:
        return []
    now = now or datetime.now(timezone.utc)
    selected = [item for item in items if item.get("conversation_id") == conversation_id]
    result = []
    for item in reversed(selected):
        try:
            created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
            if created.tzinfo is None or not timedelta(0) <= now - created <= timedelta(minutes=30):
                break
        except (KeyError, TypeError, ValueError, AttributeError):
            break
        if (item.get("skill", {}).get("id") != skill_id
                or item.get("execution", {}).get("state") != "completed"):
            break
        result.append(item)
        if len(result) == 4:
            break
    return list(reversed(result))
