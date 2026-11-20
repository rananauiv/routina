"""game_hooks: the single integration point between Routina and the game."""
from __future__ import annotations

_db = None


def bind(db) -> None:
    """Attach the open Database used to award tokens."""
    global _db
    _db = db


def on_task_completed(task_key: str) -> bool:
    """Award one token for a completion event; duplicate keys (task id + date) award nothing."""
    if _db is None or not task_key:
        return False
    try:
        return _db.award_task(str(task_key))
    except Exception:
        return False
