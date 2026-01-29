import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from html_to_semantic_json import HTMLToSemanticJSON


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


def _fetch_next_job(rest_base: str, headers: dict) -> dict | None:
    url = (
        f"{rest_base}/extraction_jobs"
        f"?status=eq.queued&order=created_at.asc&limit=1"
    )
    response = requests.get(url, headers=headers, timeout=30)
    if not response.ok:
        return None
    jobs = response.json()
    return jobs[0] if jobs else None


def _claim_job(rest_base: str, headers: dict, job_id: str) -> dict | None:
    url = f"{rest_base}/extraction_jobs?id=eq.{job_id}&status=eq.queued"
    payload = {
        "status": "processing",
        "started_at": datetime.now(timezone.utc).isoformat()
    }
    response = requests.patch(
        url,
        headers={**headers, "Prefer": "return=representation"},
        json=payload,
        timeout=30
    )
    if not response.ok:
        return None
    updated = response.json()
    return updated[0] if updated else None


def _update_job(rest_base: str, headers: dict, job_id: str, payload: dict) -> None:
    url = f"{rest_base}/extraction_jobs?id=eq.{job_id}"
    requests.patch(url, headers=headers, json=payload, timeout=30)


def main() -> None:
    supabase_url = _require_env("SUPABASE_URL").rstrip("/")
    service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    bucket = _require_env("SUPABASE_BUCKET")

    rest_base = f"{supabase_url}/rest/v1"
    storage_base = f"{supabase_url}/storage/v1"
    headers = {        "Authorization": f"Bearer {service_role_key}",
        "apikey": service_role_key,
        "Content-Type": "application/json"
    }

    print("[worker] Started, polling for jobs.", flush=True)
    while True:
        job = _fetch_next_job(rest_base, headers)
        if not job:
            time.sleep(5)
            continue

        job_id = job.get("id")
        claimed = _claim_job(rest_base, headers, job_id)
        if not claimed:
            continue

        file_paths = claimed.get("file_paths") or []
        print(f"[worker] Claimed job {job_id}, processing {len(file_paths)} file(s).", flush=True)
        # #region agent log
        _debug_log({
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": "H8",
            "location": "worker/process_jobs.py:94",
            "message": "job_claimed",
            "data": {"job_id": job_id, "paths_count": len(file_paths)},
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)
        })
        # #endregion

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        zip_id = uuid.uuid4().hex[:12]
        zip_path = f"/tmp/semantic_json_{zip_id}.zip"
        output_path = f"output/{timestamp}/semantic_json_{zip_id}.zip"

        try:
            with ZipFile(zip_path, "w", ZIP_DEFLATED) as zip_file:
                for index, path in enumerate(file_paths, start=1):
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
                raise RuntimeError(upload_response.text)

            _update_job(
                rest_base,
                headers,
                job_id,
                {
                    "status": "completed",
                    "output_path": output_path,
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }
            )
            print(f"[worker] Job {job_id} completed, output: {output_path}", flush=True)
            # #region agent log
            _debug_log({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "H9",
                "location": "worker/process_jobs.py:159",
                "message": "job_completed",
                "data": {"job_id": job_id, "output_path": output_path},
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)
            })
            # #endregion
        except Exception as exc:
            print(f"[worker] Job {job_id} failed: {exc}", flush=True)
            _update_job(
                rest_base,
                headers,
                job_id,
                {
                    "status": "failed",
                    "error": str(exc),
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }
            )


if __name__ == "__main__":
    main()
