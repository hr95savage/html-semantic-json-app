from http.server import BaseHTTPRequestHandler
import json
import os
import sys


# Ensure project root is on path so we can import the extractor
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from html_to_semantic_json import HTMLToSemanticJSON  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self._send_json({"error": "Empty request body."}, status=400)
            return

        raw_body = self.rfile.read(content_length)
        if not raw_body:
            self._send_json({"error": "Empty request body."}, status=400)
            return

        charset = "utf-8"
        content_type = self.headers.get("Content-Type", "")
        if "charset=" in content_type:
            charset = content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"

        try:
            html_content = raw_body.decode(charset, errors="replace")
        except Exception:
            self._send_json({"error": "Failed to decode request body."}, status=400)
            return

        try:
            extractor = HTMLToSemanticJSON(html_content)
            result = extractor.extract()
        except Exception as exc:
            self._send_json({"error": f"Extraction failed: {exc}"}, status=500)
            return

        self._send_json(result, status=200)

    def do_GET(self):
        self._send_json({"error": "Use POST to submit HTML."}, status=405)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
