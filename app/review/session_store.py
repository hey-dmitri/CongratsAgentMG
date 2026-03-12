from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Optional
from app.models import ReviewSession, ReviewEntry


class SessionStore:
    """Thread-safe in-memory store for ReviewSession objects."""

    def __init__(self):
        self._sessions: dict[str, ReviewSession] = {}
        self._processing: dict[str, dict] = {}  # session_id → {total, done, error}
        self._lock = Lock()

    def create(self, session: ReviewSession) -> ReviewSession:
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Optional[ReviewSession]:
        return self._sessions.get(session_id)

    def get_entry(self, session_id: str, entry_id: str) -> Optional[ReviewEntry]:
        session = self.get(session_id)
        if not session:
            return None
        return next((e for e in session.entries if e.id == entry_id), None)

    def set_processing(self, session_id: str, total: int) -> None:
        with self._lock:
            self._processing[session_id] = {"total": total, "processed": 0, "done": False, "error": ""}

    def increment_processed(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._processing:
                self._processing[session_id]["processed"] += 1

    def set_processing_done(self, session_id: str, error: str = "") -> None:
        with self._lock:
            if session_id in self._processing:
                self._processing[session_id]["done"] = True
                self._processing[session_id]["error"] = error

    def get_processing_status(self, session_id: str) -> Optional[dict]:
        return self._processing.get(session_id)

    def update_entry(self, session_id: str, entry: ReviewEntry) -> bool:
        session = self.get(session_id)
        if not session:
            return False
        with self._lock:
            for i, e in enumerate(session.entries):
                if e.id == entry.id:
                    session.entries[i] = entry
                    return True
        return False

    def get_recent_approved(self, limit: int = 20) -> list[dict]:
        """Return approved/edited entries across all sessions, most recent first."""
        results = []
        for session in self._sessions.values():
            for entry in session.entries:
                if entry.status in ("approved", "edited"):
                    approved_at = entry.approved_at or session.created_at
                    try:
                        dt = datetime.fromisoformat(approved_at)
                        approved_at_display = dt.strftime("%a %b %-d, %-I:%M %p")
                    except Exception:
                        approved_at_display = ""
                    results.append({
                        "session_id": session.session_id,
                        "entry_id": entry.id,
                        "race_name": session.race_name,
                        "race_date": session.race_date,
                        "runner_name": entry.finisher.full_name,
                        "category": entry.category,
                        "place": entry.place,
                        "instagram_handle": entry.final_instagram_handle,
                        "instagram_text": entry.final_instagram_text,
                        "status": entry.status,
                        "created_at": approved_at,
                        "approved_at_display": approved_at_display,
                    })
        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results[:limit]


# Singleton
store = SessionStore()
