import json
import mimetypes
import os
import queue
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

DEFAULT_QUESTIONS = [
    "What is the International Student Office?",
    "How do I apply for Erasmus?",
    "What language courses are available?",
    "How do I find housing?",
    "What health insurance do I need?",
    "How do I study abroad?",
    "👋 Goodbye / That's all!",
]


class _TabletHandler(BaseHTTPRequestHandler):
    # serves tablet content (text, images, ...) to Pepper's browser
    local_image_dir: str = None
    touch_queue: queue.Queue = None
    base_dir: Path = None
    state_holder: list = ["splash"]
    questions_holder: list = [DEFAULT_QUESTIONS]

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/api/state":
            self._respond_json({"state": self.state_holder[0]})

        elif path == "/api/questions":
            self._respond_json({"questions": self.questions_holder[0]})

        if path == "/text":
            text = params.get("content", [""])[0]
            text = urllib.parse.unquote(text)
            text = (text
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                    .replace("'", "&#39;")
                    .replace("\n", "<br>"))
            html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="display:flex;justify-content:center;align-items:center;
             height:100vh;margin:0;background:#ffffff;">
  <p style="font-size:60px;text-align:center;font-family:sans-serif;
            padding:40px;word-wrap:break-word;">{text}</p>
</body>
</html>"""
            self._respond(200, "text/html", html.encode("utf-8"))

        elif path.startswith("/image/"):
            filename = path[len("/image/"):]
            filepath = os.path.join(self.local_image_dir, filename) if self.local_image_dir else filename
            if os.path.isfile(filepath):
                mime, _ = mimetypes.guess_type(filepath)
                mime = mime or "application/octet-stream"
                with open(filepath, "rb") as f:
                    data = f.read()
                self._respond(200, mime, data)
            else:
                self._respond(404, "text/plain", b"File not found")

        elif path == "/touch":
            q = params.get("q", [None])[0]
            if q:
                if self.touch_queue is not None:
                    self.touch_queue.put(q.strip())
                self._respond_json({"ok": True})
            else:
                self._respond_json({"ok": False}, status=400)

        elif path in ("/", "/index.html"):
            filepath = self.base_dir / "assets" / "tablet" / "index.html"
            if filepath.is_file():
                with open(filepath, "rb") as f:
                    data = f.read()
                self._respond(200, "text/html", data)
            else:
                self._respond(404, "text/plain", b"File not found")

        elif path == "/clear":
            self._respond(200, "text/html", b"<!DOCTYPE html><html><body style='background:#fff;'></body></html>")

        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_json(self, data: dict, status: int = 200):
        self._respond(status, "application/json", json.dumps(data).encode("utf-8"))

class TabletServer:
    def __init__(self,local_ip: str, port: int = 8080, local_image_dir: str = None):
        self.local_ip = local_ip
        self.port = port
        self._touch_queue: queue.Queue = queue.Queue()
        _TabletHandler.local_image_dir = local_image_dir
        _TabletHandler.touch_queue = self._touch_queue
        _TabletHandler.base_dir = Path(__file__).resolve().parents[1]
        _TabletHandler.state_holder = ["splash"]
        _TabletHandler.questions_holder = [DEFAULT_QUESTIONS]
        self._server = HTTPServer(("0.0.0.0",port),_TabletHandler)
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        print(f"Tablet server running on {local_ip}:{port}")

    def url(self, path: str) -> str:
        return f"http://{self.local_ip}:{self.port}{path}"

    def set_state(self, state: str):
        _TabletHandler.state_holder[0] = state

    def set_questions(self, questions: list[str]):
        _TabletHandler.questions_holder[0] = list(questions)

    def get_touch_input(self, timeout: float = None) -> str | None:
        try:
            if timeout is None:
                return self._touch_queue.get()
            return self._touch_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait_for_touch(self, timeout: float = None) -> str | None:
        return self.get_touch_input(timeout=timeout)
    
    def stop(self):
        self._server.shutdown()