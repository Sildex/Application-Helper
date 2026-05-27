"""Shared activity log – imported by search_engine, ui, and debug window."""
import time
from collections import deque

_ACTIVITY_LOG: deque = deque(maxlen=200)


def _log_activity(msg: str, level: str = "info") -> None:
    _ACTIVITY_LOG.append({"ts": time.strftime("%H:%M:%S"), "msg": msg, "level": level})
