# tablet_server.py — Custom HTTP server for Pepper's tablet
#
# Serves the interactive tablet page and handles:
#   GET /                   → index.html
#   GET /assets/*           → static files (images etc.)
#   GET /api/state          → {"state": "idle"}
#   GET /api/questions      → {"questions": [...]}
#   GET /touch?q=...        → visitor touched a button → added to queue
#
# Usage:
#   server = TabletServer(local_ip, port, base_dir)
#   server.start()
#   server.set_state("speaking")
#   server.set_questions(QUESTIONS["erasmus"])
#   q = server.get_touch_input()   # None if nothing yet
#   server.stop()

import json
import logging
import queue
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import mimetypes

log = logging.getLogger("tablet")

# ── Default question sets ──────────────────────────────────────────────────────

QUESTIONS = {
    "default": [
        "What is the International Student Office?",
        "How do I apply for Erasmus?",
        "What language courses are available?",
        "How do I find housing?",
        "What health insurance do I need?",
        "How do I study abroad?",
    ],
    "erasmus": [
        "Which countries can I go to?",
        "How much Erasmus funding do I get?",
        "When is the application deadline?",
        "How are credits recognised?",
        "What about non-EU exchanges (DAAD)?",
        "← Back to main menu",
    ],
    "partner_universities": [
        "Which European partners do you have?",
        "Are there partners in the USA or Canada?",
        "Any partners in Asia?",
        "What about South America?",
        "How do I apply for a partner university?",
        "← Back to main menu",
    ],
    "language_courses": [
        "What German courses are available?",
        "What is the Sprachtandem programme?",
        "How do I register for a course?",
        "Are there intensive summer courses?",
        "What language certificates can I get?",
        "← Back to main menu",
    ],
    "housing": [
        "How do student dormitories work?",
        "How do I find a private room?",
        "How much does accommodation cost?",
        "What is address registration (Anmeldung)?",
        "← Back to main menu",
    ],
    "health_insurance": [
        "What insurance do EU students need?",
        "What insurance do non-EU students need?",
        "Which providers do you recommend?",
        "When do I need to get insurance?",
        "← Back to main menu",
    ],
    "studying_abroad": [
        "What is the Erasmus+ programme?",
        "How do I apply to go abroad?",
        "Which partner universities exist?",
        "Can I get a scholarship?",
        "How are my credits recognised?",
        "← Back to main menu",
    ],
    "outgoing_process": [
        "What are the application steps?",
        "Who is my contact at the ISO?",
        "What is a Learning Agreement?",
        "How does credit recognition work?",
        "← Back to main menu",
    ],
    "redirect": [
        "What is the ISO?",
        "How do I apply for Erasmus?",
        "Language courses at Ostfalia?",
        "Housing information?",
        "Health insurance questions?",
        "How to study abroad?",
    ],
}

# Add goodbye to all question sets
_GOODBYE = "\U0001f44b Goodbye / That\'s all, thank you!"
for _k in list(QUESTIONS.keys()):
    if _GOODBYE not in QUESTIONS[_k]:
        QUESTIONS[_k].append(_GOODBYE)

# Map LLM topic keys → question set keys
TOPIC_TO_QUESTIONS = {
    "erasmus":              "erasmus",
    "partner_universities": "partner_universities",
    "studying_abroad":      "studying_abroad",
    "outgoing_process":     "outgoing_process",
    "europe_partners":      "erasmus",
    "new_erasmus_partners": "erasmus",
    "non_eu_partners":      "partner_universities",
    "americas_asia":        "partner_universities",
    "language_courses":     "language_courses",
    "housing":              "housing",
    "health_insurance":     "health_insurance",
    "redirect":             "redirect",
    "welcome":              "default",
    "farewell":             "default",
    "other":                "default",
}


def questions_for_topic(topic: str) -> list[str]:
    key = TOPIC_TO_QUESTIONS.get(topic, "default")
    return QUESTIONS.get(key, QUESTIONS["default"])


# ── HTTP request handler ───────────────────────────────────────────────────────

class _TabletHandler(BaseHTTPRequestHandler):

    # Injected by TabletServer before starting
    touch_queue: queue.Queue = None
    state_holder: list = ["idle"]          # [0] = current state string
    questions_holder: list = [QUESTIONS["default"]]  # [0] = current list

    def log_message(self, format, *args):
        # Suppress default access log — too noisy
        log.debug("Tablet HTTP: " + format % args)

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        params = parse_qs(parsed.query)

        # ── API endpoints ──────────────────────────────────────────────────────

        if path == "/api/state":
            self._json({"state": self.state_holder[0]})

        elif path == "/api/questions":
            self._json({"questions": self.questions_holder[0]})

        elif path == "/touch":
            q        = params.get("q", [None])[0]
            redirect = params.get("redirect", [None])[0]
            if q:
                log.info("Tablet touch: %s", q)
                self.touch_queue.put(q.strip())
                if redirect:
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self._json({"ok": True})
            else:
                self._json({"ok": False}, status=400)

        # ── Static files ───────────────────────────────────────────────────────

        elif path in ("/", "/index.html"):
            self._serve_file(self.server.base_dir / "assets" / "tablet" / "index.html")

        elif path.startswith("/assets/"):
            self._serve_file(self.server.base_dir / path.lstrip("/"))

        else:
            self._text("Not found", status=404)

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text: str, status: int = 200):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filepath: Path):
        if not filepath.exists():
            self._text(f"File not found: {filepath}", status=404)
            return
        mime, _ = mimetypes.guess_type(str(filepath))
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


# ── TabletServer ───────────────────────────────────────────────────────────────

class TabletServer:
    """
    Runs the interactive tablet HTTP server in a background thread.
    Thread-safe — all public methods can be called from any thread.
    """

    def __init__(self, local_ip: str, port: int, base_dir: str | Path):
        self._ip       = local_ip
        self._port     = port
        self._base_dir = Path(base_dir)
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

        self._touch_queue:     queue.Queue = queue.Queue()
        self._state_holder:    list        = ["idle"]
        self._questions_holder: list       = [QUESTIONS["default"]]

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the HTTP server in a daemon background thread."""
        try:
            # Inject shared state into the handler class
            _TabletHandler.touch_queue      = self._touch_queue
            _TabletHandler.state_holder     = self._state_holder
            _TabletHandler.questions_holder = self._questions_holder

            self._server = HTTPServer(("0.0.0.0", self._port), _TabletHandler)
            self._server.base_dir = self._base_dir

            self._thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="tablet-server",
            )
            self._thread.start()
            log.info("Tablet server started at http://%s:%d", self._ip, self._port)
            return True
        except Exception as e:
            log.error("Tablet server failed to start: %s", e)
            return False

    def stop(self):
        if self._server:
            self._server.shutdown()
            log.info("Tablet server stopped.")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── State control ──────────────────────────────────────────────────────────

    def set_state(self, state: str):
        """Update display state: idle | speaking | listening | thinking"""
        self._state_holder[0] = state

    def set_questions(self, questions: list[str]):
        """Replace the visible question buttons."""
        self._questions_holder[0] = questions

    def set_questions_for_topic(self, topic: str):
        """Shortcut — picks the right question set for an LLM topic."""
        self.set_questions(questions_for_topic(topic))

    def reset_to_default(self):
        self.set_questions(QUESTIONS["default"])
        self.set_state("idle")

    # ── Touch input ────────────────────────────────────────────────────────────

    def get_touch_input(self, timeout: float = 0) -> str | None:
        """
        Returns the next question the visitor tapped, or None.
        Set timeout > 0 to block briefly.
        """
        try:
            return self._touch_queue.get(timeout=timeout) if timeout > 0 else \
                   self._touch_queue.get_nowait()
        except queue.Empty:
            return None

    def clear_touch_queue(self):
        while not self._touch_queue.empty():
            try:
                self._touch_queue.get_nowait()
            except queue.Empty:
                break

    # ── URL helpers ────────────────────────────────────────────────────────────

    def url(self, path: str = "/") -> str:
        return f"http://{self._ip}:{self._port}{path}"

    def tablet_page_url(self) -> str:
        return self.url("/")
