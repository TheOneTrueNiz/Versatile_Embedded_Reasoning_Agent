"""
VERA 2.0 Session Management
=============================

Channel-aware session routing with JSONL transcript persistence.
Ported from Moltbot's session-key and session-store patterns.
"""

from sessions.types import SessionEntry, SessionScope
from sessions.keys import derive_link_session_key, derive_session_key, normalize_link_id
from sessions.store import SessionStore

__all__ = [
    "SessionEntry",
    "SessionScope",
    "derive_link_session_key",
    "derive_session_key",
    "normalize_link_id",
    "SessionStore",
]
