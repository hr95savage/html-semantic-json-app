from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED
import json
import os
import re
import uuid

import requests

from html_to_semantic_json import HTMLToSemanticJSON


def _require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise ValueError(f"Missing environment variable: {key}")
    return value


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "").strip()
    if not base:
        return "upload.html"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return base[:120] or "upload.html"


def _safe_output_name(path: str, index: int) -> str:
    base = os.path.basename(path) or f"file_{index}"
    base = base.rsplit(".", 1)[0]
    base = "".join(ch if ch.isalnum() or ch in ("_", "-", ".") else "_" for ch in base)
    if not base:
        base = f"file_{index}"
    return f"{base}.json"


class DevHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, payload, status=200):
        self._set_headers(status)
        self.wfile.write(json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"))

    def _read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return None, "Empty request body."
        raw_body = self.rfile.read(content_length)
        try:
            return json.loads(raw_body), None
        except json.JSONDecodeError:
            return None, "Invalid JSON payload."

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_POST(self):
        if self.path == "/extract":
            return self._handle_extract()
        if self.path == "/api/supabase/sign":
            return self._handle_supabase_sign()
        if self.path == "/api/supabase/process":
            return self._handle_supabase_process()

        self._send_json({"error": "Not found"}, status=404)

    def _handle_extract(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self._send_json({"error": "Empty request body."}, status=400)
            return

        raw_body = self.rfile.read(content_length)
        html_content = raw_body.decode("utf-8", errors="replace")
        try:
            result = HTMLToSemanticJSON(html_content).extract()
            self._send_json(result, status=200)
        except Exception as exc:
            self._send_json({"error": f"Extraction failed: {exc}"}, status=500)

    def _handle_supabase_sign(self):
        payload, error = self._read_json()
        if error:
            self._send_json({"error": error}, status=400)
            return

        files = payload.get("files") if isinstance(payload, dict) else None
        if not isinstance(files, list) or not files:
            self._send_json({"error": "files must be a non-empty array."}, status=400)
            return

        try:
            supabase_url = _require_env("SUPABASE_URL").rstrip("/")
            service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
            bucket = _require_env("SUPABASE_BUCKET")
        except ValueError as exc:
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

            sign_url = (
                f"{storage_base}/object/upload/sign/"
                f"{quote(bucket, safe='')}/{quote(path, safe='/')}"
            )
            headers = {
                "Authorization": f"Bearer {service_role_key}",
                "apikey": service_role_key,
                "Content-Type": "application/json"
            }
            body = {"expiresIn": 3600}
            response = requests.post(sign_url, headers=headers, json=body, timeout=30)
            if not response.ok:
                self._send_json(
                    {"error": "Failed to sign upload.", "details": response.text},
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

        self._send_json({"uploads": uploads}, status=200)

    def _handle_supabase_process(self):
        payload, error = self._read_json()
        if error:
            self._send_json({"error": error}, status=400)
            return

        paths = payload.get("paths") if isinstance(payload, dict) else None
        if not isinstance(paths, list) or not paths:
            self._send_json({"error": "paths must be a non-empty array."}, status=400)
            return

        try:
            supabase_url = _require_env("SUPABASE_URL").rstrip("/")
            service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
            bucket = _require_env("SUPABASE_BUCKET")
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=500)
            return

        storage_base = f"{supabase_url}/storage/v1"

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        zip_id = uuid.uuid4().hex[:12]
        zip_path = f"/tmp/semantic_json_{zip_id}.zip"

        headers = {
            "Authorization": f"Bearer {service_role_key}",
            "apikey": service_role_key
        }

        with ZipFile(zip_path, "w", ZIP_DEFLATED) as zip_file:
            for index, path in enumerate(paths, start=1):
                if not isinstance(path, str) or not path.strip():
                    continue
                cleaned_path = path.strip().lstrip("/")
                object_url = (
                    f"{storage_base}/object/"
                    f"{quote(bucket, safe='')}/{quote(cleaned_path, safe='/')}"
                )
                response = requests.get(object_url, headers=headers, timeout=120)
                if not response.ok:
                    error_payload = {
                        "error": f"Failed to download {cleaned_path}",
                        "details": response.text
                    }
                    zip_file.writestr(
                        _safe_output_name(cleaned_path, index),
                        json.dumps(error_payload, indent=2, ensure_ascii=False)
                    )
                    continue

                html_text = response.content.decode("utf-8", errors="replace")
                try:
                    extractor = HTMLToSemanticJSON(html_text)
                    result = extractor.extract()
                except Exception as exc:
                    result = {"error": f"Extraction failed: {exc}"}

                zip_file.writestr(
                    _safe_output_name(cleaned_path, index),
                    json.dumps(result, indent=2, ensure_ascii=False)
                )

        output_path = f"output/{timestamp}/semantic_json_{zip_id}.zip"
        upload_url = (
            f"{storage_base}/object/"
            f"{quote(bucket, safe='')}/{quote(output_path, safe='/')}"
        )
        upload_headers = {
            "Authorization": f"Bearer {service_role_key}",
            "apikey": service_role_key,
            "Content-Type": "application/zip",
            "x-upsert": "true"
        }
        with open(zip_path, "rb") as zip_file:
            upload_response = requests.post(
                upload_url, headers=upload_headers, data=zip_file, timeout=120
            )

        if not upload_response.ok:
            self._send_json(
                {
                    "error": "Failed to upload ZIP to Supabase.",
                    "details": upload_response.text
                },
                status=502
            )
            return

        sign_url = (
            f"{storage_base}/object/sign/"
            f"{quote(bucket, safe='')}/{quote(output_path, safe='/')}"
        )
        sign_headers = {
            "Authorization": f"Bearer {service_role_key}",
            "apikey": service_role_key,
            "Content-Type": "application/json"
        }
        sign_body = {"expiresIn": 3600}
        sign_response = requests.post(
            sign_url, headers=sign_headers, json=sign_body, timeout=30
        )
        if not sign_response.ok:
            self._send_json(
                {
                    "error": "Failed to sign output ZIP.",
                    "details": sign_response.text
                },
                status=502
            )
            return

        sign_payload = sign_response.json()
        signed_url = (
            sign_payload.get("signedUrl")
            or sign_payload.get("signedURL")
            or sign_payload.get("url")
        )
        if signed_url and signed_url.startswith("/"):
            signed_url = f"{storage_base}{signed_url}"

        self._send_json(
            {
                "downloadUrl": signed_url,
                "outputPath": output_path
            },
            status=200
        )


def run():
    port = int(os.environ.get("DEV_EXTRACT_PORT", "5005"))
    server = HTTPServer(("0.0.0.0", port), DevHandler)
    print(f"Dev API running on http://localhost:{port}")
    print(f"- POST http://localhost:{port}/extract")
    print(f"- POST http://localhost:{port}/api/supabase/sign")
    print(f"- POST http://localhost:{port}/api/supabase/process")
    server.serve_forever()


if __name__ == "__main__":
    run()
