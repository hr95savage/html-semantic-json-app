from http.server import BaseHTTPRequestHandler
import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import quote, urlparse, parse_qs

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


class handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        job_id = query.get("job_id", [None])[0]
        if not job_id:
            _api_log("WARN", "jobs_get_missing_job_id")
            self._send_json({"error": "job_id is required."}, status=400)
            return

        _api_log("INFO", "jobs_get_start", job_id=job_id)
        try:
            supabase_url = _require_env("SUPABASE_URL").rstrip("/")
            service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
            bucket = _require_env("SUPABASE_BUCKET")
        except ValueError as exc:
            _api_log("ERROR", "jobs_get_env_failed", error=str(exc))
            self._send_json({"error": str(exc)}, status=500)
            return

        rest_headers = {
            "Authorization": f"Bearer {service_role_key}",
            "apikey": service_role_key,
            "Content-Type": "application/json"
        }
        job_url = (
            f"{supabase_url}/rest/v1/extraction_jobs"
            f"?id=eq.{job_id}&select=id,status,output_path,error"
        )
        try:
            response = requests.get(job_url, headers=rest_headers, timeout=30)
        except Exception as e:
            _api_log("ERROR", "jobs_get_request_failed", job_id=job_id, error=str(e))
            self._send_json({"error": "Failed to fetch job.", "details": str(e)}, status=502)
            return
        _api_log("INFO", "jobs_get_response", job_id=job_id, status=response.status_code)
        # #region agent log
        _debug_log({
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": "H6",
            "location": "api/jobs.py:63",
            "message": "job_fetch",
            "data": {"status": response.status_code},
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)
        })
        # #endregion
        if not response.ok:
            _api_log("ERROR", "jobs_get_bad_response", job_id=job_id, status=response.status_code, body=(response.text[:300] if response.text else None))
            self._send_json(
                {"error": "Failed to fetch job.", "details": response.text},
                status=502
            )
            return

        jobs = response.json()
        if not jobs:
            _api_log("WARN", "jobs_get_not_found", job_id=job_id)
            self._send_json({"error": "Job not found."}, status=404)
            return

        job = jobs[0]
        status = job.get("status")
        output_path = job.get("output_path")
        error = job.get("error")
        _api_log("INFO", "jobs_get_ok", job_id=job_id, job_status=status)
        payload = {"jobId": job_id, "status": status, "error": error}

        if status == "completed" and output_path:
            storage_base = f"{supabase_url}/storage/v1"
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
            try:
                sign_response = requests.post(
                    sign_url, headers=sign_headers, json=sign_body, timeout=30
                )
            except Exception as e:
                _api_log("ERROR", "jobs_sign_request_failed", job_id=job_id, error=str(e))
            else:
                _api_log("INFO", "jobs_sign_response", job_id=job_id, status=sign_response.status_code)
                if sign_response.ok:
                    sign_payload = sign_response.json()
                    signed_url = (
                        sign_payload.get("signedUrl")
                        or sign_payload.get("signedURL")
                        or sign_payload.get("url")
                    )
                    if signed_url and signed_url.startswith("/"):
                        signed_url = f"{storage_base}{signed_url}"
                    payload["downloadUrl"] = signed_url
                    _api_log("INFO", "jobs_sign_ok", job_id=job_id)
                else:
                    _api_log("ERROR", "jobs_sign_bad_response", job_id=job_id, status=sign_response.status_code, body=(sign_response.text[:200] if sign_response.text else None))

        self._send_json(payload, status=200)

    def do_POST(self):
        self._send_json({"error": "Use GET."}, status=405)
