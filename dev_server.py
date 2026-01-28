from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from html_to_semantic_json import HTMLToSemanticJSON


class DevHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_POST(self):
        if self.path != "/extract":
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode("utf-8"))
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self._set_headers(400)
            self.wfile.write(json.dumps({"error": "Empty request body"}).encode("utf-8"))
            return

        raw_body = self.rfile.read(content_length)
        html_content = raw_body.decode("utf-8", errors="replace")
        try:
            result = HTMLToSemanticJSON(html_content).extract()
            self._set_headers(200)
            self.wfile.write(json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8"))
        except Exception as exc:
            self._set_headers(500)
            self.wfile.write(json.dumps({"error": f"Extraction failed: {exc}"}).encode("utf-8"))


def run():
    port = int(os.environ.get("DEV_EXTRACT_PORT", "5005"))
    server = HTTPServer(("0.0.0.0", port), DevHandler)
    print(f"Dev extractor running on http://localhost:{port}/extract")
    server.serve_forever()


if __name__ == "__main__":
    run()
