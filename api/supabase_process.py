from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from html_to_semantic_json import HTMLToSemanticJSON


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
                encoded_bucket = quote(bucket, safe="")
                encoded_path = quote(cleaned_path, safe="/")
                object_url = (
                    f"{storage_base}/object/{encoded_bucket}/{encoded_path}"
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

    def do_GET(self):
        self._send_json({"error": "Use POST."}, status=405)
