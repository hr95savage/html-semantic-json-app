from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
import json
import os
import re
import sys
import uuid
from urllib.parse import quote

import requests


def _api_log(level: str, event: str, **kwargs) -> None:
    """Structured stdout log for Vercel; all keys JSON-serializable."""
    payload = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "event": event, **{k: v for k, v in kwargs.items() if v is not None}}
    try:
        line = json.dumps(payload, default=str, ensure_ascii=False)
    except Exception:
        line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "level": level, "event": event})
    print(line, flush=True)
    sys.stdout.flush()


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "").strip()
    if not base:
        return "upload.html"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return base[:120] or "upload.html"


def _require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise ValueError(f"Missing environment variable: {key}")
    return value


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

        files = payload.get("files")
        if not isinstance(files, list) or not files:
            _api_log("WARN", "sign_invalid_files")
            self._send_json({"error": "files must be a non-empty array."}, status=400)
            return

        _api_log("INFO", "sign_start", files_count=len(files))
        try:
            supabase_url = _require_env("SUPABASE_URL").rstrip("/")
            service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
            bucket = _require_env("SUPABASE_BUCKET")
        except ValueError as exc:
            _api_log("ERROR", "sign_env_failed", error=str(exc))
            self._send_json({"error": str(exc)}, status=500)
            return

        storage_base = f"{supabase_url}/storage/v1"

        prefix = payload.get("prefix") or "uploads"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        uploads = []

        for file_info in files:
            if not isinstance(file_info, dict):
                continue
            original_name = file_info.get("name", "upload.html")
            safe_name = _sanitize_filename(original_name)
            unique_id = uuid.uuid4().hex[:12]
            path = f"{prefix}/{timestamp}/{unique_id}_{safe_name}"

            encoded_bucket = quote(bucket, safe="")
            encoded_path = quote(path, safe="/")
            sign_url = (
                f"{storage_base}/object/upload/sign/"
                f"{encoded_bucket}/{encoded_path}"
            )
            headers = {
                "Authorization": f"Bearer {service_role_key}",
                "apikey": service_role_key,
                "Content-Type": "application/json"
            }
            body = {"expiresIn": 3600}
            _api_log("INFO", "sign_request", path=path)
            try:
                response = requests.post(sign_url, headers=headers, json=body, timeout=30)
            except Exception as e:
                _api_log("ERROR", "sign_request_failed", path=path, error=str(e))
                self._send_json({"error": "Failed to sign upload.", "details": str(e)}, status=502)
                return
            _api_log("INFO", "sign_response", path=path, status=response.status_code)
            if not response.ok:
                _api_log("ERROR", "sign_bad_response", path=path, status=response.status_code, body=(response.text[:300] if response.text else None))
                self._send_json(
                    {
                        "error": "Failed to sign upload.",
                        "details": response.text
                    },
                    status=502
                )
                return

            signed_payload = response.json()
            signed_url = (
                signed_payload.get("signedUrl")
                or signed_payload.get("signedURL")
                or signed_payload.get("url")
            )
            if not signed_url:
                _api_log("ERROR", "sign_no_url", path=path)
                self._send_json(
                    {"error": "Signed URL missing from Supabase response."},
                    status=502
                )
                return

            if signed_url.startswith("/"):
                signed_url = f"{storage_base}{signed_url}"

            uploads.append(
                {
                    "path": path,
                    "signedUrl": signed_url,
                    "contentType": file_info.get("contentType") or "text/html"
                }
            )

        _api_log("INFO", "sign_ok", uploads_count=len(uploads))
        self._send_json({"uploads": uploads}, status=200)

    def do_GET(self):
        self._send_json({"error": "Use POST."}, status=405)
