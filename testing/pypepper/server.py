import mimetypes
import os
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler


class _TabletHandler(BaseHTTPRequestHandler):
    # serves tablet content (text, images, ...) to Pepper's browser
    local_image_dir: str = None

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

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

class TabletServer:
    def __init__(self,local_ip: str, port: int = 8080, local_image_dir: str = None):
        self.local_ip = local_ip
        self.port = port
        _TabletHandler.local_image_dir = local_image_dir
        self._server = HTTPServer(("0.0.0.0",port),_TabletHandler)
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        print(f"Tablet server running on {local_ip}:{port}")

    def url(self, path: str) -> str:
        return f"http://{self.local_ip}:{self.port}{path}"
    
    def stop(self):
        self._server.shutdown()