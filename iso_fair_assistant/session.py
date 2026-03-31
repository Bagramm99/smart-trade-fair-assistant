# session.py — visitor session tracking via QR code IDs
#
# Keeps an in-memory record of who has already been helped today.
# Resets when the program restarts (fine for a one-day demo).

import time
import random
import string
import logging

log = logging.getLogger("session")


class SessionManager:
    def __init__(self):
        # { visitor_id: { "first_seen": timestamp, "topics": [str], "helped": bool } }
        self._sessions: dict[str, dict] = {}

    # ── QR code ID generation ──────────────────────────────────────────────────

    @staticmethod
    def generate_id() -> str:
        """
        Generate a short anonymous visitor ID like 'STU-4X7K'.
        In the demo, print a set of these as QR codes before the fair.
        Use any QR generator: qr.io, qrcode Python library, etc.
        """
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return f"STU-{suffix}"

    # ── Session logic ─────────────────────────────────────────────────────────

    def is_known(self, visitor_id: str) -> bool:
        return visitor_id in self._sessions

    def is_already_helped(self, visitor_id: str) -> bool:
        return self._sessions.get(visitor_id, {}).get("helped", False)

    def start_session(self, visitor_id: str):
        """Register a new visitor or re-open an existing session."""
        if visitor_id not in self._sessions:
            self._sessions[visitor_id] = {
                "first_seen": time.time(),
                "topics": [],
                "helped": False,
            }
            log.info("New session: %s", visitor_id)
        else:
            log.info("Returning visitor: %s", visitor_id)

    def record_topic(self, visitor_id: str, topic: str):
        """Track which topics were discussed with this visitor."""
        if visitor_id in self._sessions:
            topics = self._sessions[visitor_id]["topics"]
            if topic not in topics:
                topics.append(topic)

    def close_session(self, visitor_id: str):
        """Mark the visitor as helped and close their session."""
        if visitor_id in self._sessions:
            self._sessions[visitor_id]["helped"] = True
            log.info("Session closed: %s | Topics: %s",
                     visitor_id, self._sessions[visitor_id]["topics"])

    def get_topics(self, visitor_id: str) -> list[str]:
        return self._sessions.get(visitor_id, {}).get("topics", [])

    def stats(self) -> dict:
        total   = len(self._sessions)
        helped  = sum(1 for s in self._sessions.values() if s["helped"])
        return {"total_visitors": total, "helped": helped, "still_active": total - helped}
