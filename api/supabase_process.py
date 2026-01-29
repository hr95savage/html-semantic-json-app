from http.server import BaseHTTPRequestHandler
import json
import os
import uuid
from datetime import datetime, timezone

import requests

def _debug_log(payload: dict) -> None:
    try:
        with open(
            "/Users/hunterricks/Savage/Software/SEO/On-page Scraper pt. 1 - JSON Parsor/.cursor/debug.log",
            "a",
            encoding="utf-8"
        ) as log_file:
            log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise ValueError(f"Missing environment variable: {key}")
    return value


def _safe_output_name(path: str, index: int) -> str:
    base = os.path.basename(path) or f"file_{index}"
    base = base.rsplit(".", 1)[0]
    base = "".join(ch if ch.isalnum() or ch in ("_", "-", ".") else "_" for ch in base)
    if not base:
        base = f"file_{index}"
    return f"{base}.json"


class handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        if content_length <= 0:
            self._send_json({"error": "Empty request body."}, status=400)
            return

        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON payload."}, status=400)
            return

        paths = payload.get("paths")
        if not isinstance(paths, list) or not paths:
            self._send_json({"error": "paths must be a non-empty array."}, status=400)
            return

        # #region agent log
        _debug_log({
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": "H1",
            "location": "api/supabase_process.py:68",
            "message": "process_start",
            "data": {"paths_count": len(paths)},
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)
        })
        # #endregion

        try:
            supabase_url = _require_env("SUPABASE_URL").rstrip("/")
            service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=500)
            return

        rest_headers = {
            "Authorization": f"Bearer {service_role_key}",
            "apikey": service_role_key,
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        job_id = str(uuid.uuid4())
        job_payload = {
            "id": job_id,
            "status": "queued",
            "file_paths": paths
        }
        create_response = requests.post(
            f"{supabase_url}/rest/v1/extraction_jobs",
            headers=rest_headers,
            json=job_payload,
            timeout=30
        )
        # #region agent log
        _debug_log({
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": "H5",
            "location": "api/supabase_process.py:111",
            "message": "job_create",
            "data": {"status": create_response.status_code},
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)
        })
        # #endregion
        if not create_response.ok:
            self._send_json(
                {
                    "error": "Failed to create job.",
                    "details": create_response.text
                },
                status=502
            )
            return

        self._send_json(
            {
                "jobId": job_id,
                "status": "queued"
            },
            status=202
        )

    def do_GET(self):
        self._send_json({"error": "Use POST."}, status=405)
