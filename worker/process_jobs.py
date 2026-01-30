import json
import os
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from urllib.parse import quote
from datetime import timedelta
from zipfile import ZipFile, ZIP_DEFLATED

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from html_to_semantic_json import HTMLToSemanticJSON


def _log(level: str, event: str, **kwargs) -> None:
    """Structured stdout log for Render; all keys must be JSON-serializable."""
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
        **{k: v for k, v in kwargs.items() if v is not None},
    }
    try:
        line = json.dumps(payload, default=str, ensure_ascii=False)
    except Exception:
        line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "level": level, "event": event, "error": "log_serialize_failed"})
    print(line, flush=True)


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
    try:
        response = requests.get(url, headers=headers, timeout=30)
    except Exception as e:
        _log("ERROR", "fetch_jobs_request_failed", error=str(e))
        return None
    if not response.ok:
        _log("WARN", "fetch_jobs_bad_response", status=response.status_code, body=(response.text[:500] if response.text else None))
        return None
    jobs = response.json()
    if not jobs:
        return None
    _log("INFO", "fetch_jobs_got_job", job_id=str(jobs[0].get("id")))
    return jobs[0]


def _claim_job(rest_base: str, headers: dict, job_id: str) -> dict | None:
    url = f"{rest_base}/extraction_jobs?id=eq.{job_id}&status=eq.queued"
    payload = {
        "status": "processing",
        "started_at": datetime.now(timezone.utc).isoformat()
    }
    try:
        response = requests.patch(
            url,
            headers={**headers, "Prefer": "return=representation"},
            json=payload,
            timeout=30
        )
    except Exception as e:
        _log("ERROR", "claim_job_request_failed", job_id=job_id, error=str(e))
        return None
    if not response.ok:
        _log("WARN", "claim_job_bad_response", job_id=job_id, status=response.status_code, body=(response.text[:500] if response.text else None))
        return None
    updated = response.json()
    if not updated:
        _log("WARN", "claim_job_empty_response", job_id=job_id)
        return None
    _log("INFO", "claim_job_ok", job_id=job_id, file_count=len(updated[0].get("file_paths") or []))
    return updated[0]


def _update_job(rest_base: str, headers: dict, job_id: str, payload: dict) -> None:
    url = f"{rest_base}/extraction_jobs?id=eq.{job_id}"
    try:
        r = requests.patch(url, headers=headers, json=payload, timeout=30)
        if not r.ok:
            _log("ERROR", "update_job_bad_response", job_id=job_id, status=r.status_code, body=(r.text[:300] if r.text else None))
    except Exception as e:
        _log("ERROR", "update_job_request_failed", job_id=job_id, error=str(e))


# Jobs stuck in "processing" (e.g. worker restarted mid-job) are marked failed so UI and worker can recover.
STALE_PROCESSING_MINUTES = 15


def _mark_stale_processing_jobs_failed(rest_base: str, headers: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_PROCESSING_MINUTES)).isoformat()
    url = (
        f"{rest_base}/extraction_jobs"
        f"?status=eq.processing&started_at=lt.{quote(cutoff, safe='')}&select=id"
    )
    response = requests.get(url, headers=headers, timeout=30)
    if not response.ok or not response.json():
        return
    for row in response.json():
        job_id = row.get("id")
        if job_id:
            _update_job(
                rest_base,
                headers,
                job_id,
                {
                    "status": "failed",
                    "error": "Job timed out (worker restarted or interrupted). Please try again.",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            print(f"[worker] Marked stale job {job_id} as failed.", flush=True)


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

    _log("INFO", "worker_started")
    print("[worker] Started, polling for jobs.", flush=True)
    while True:
        _mark_stale_processing_jobs_failed(rest_base, headers)
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
            _log("INFO", "job_zip_start", job_id=job_id, zip_path=zip_path, file_count=len(file_paths))
            with ZipFile(zip_path, "w", ZIP_DEFLATED) as zip_file:
                for index, path in enumerate(file_paths, start=1):
                    if not isinstance(path, str) or not path.strip():
                        _log("WARN", "job_file_skip", job_id=job_id, index=index, reason="empty_path")
                        continue
                    cleaned_path = path.strip().lstrip("/")
                    _log("INFO", "job_file_download_start", job_id=job_id, index=index, path=cleaned_path)
                    object_url = (
                        f"{storage_base}/object/"
                        f"{quote(bucket, safe='')}/{quote(cleaned_path, safe='/')}"
                    )
                    try:
                        response = requests.get(object_url, headers=headers, timeout=120)
                    except Exception as e:
                        _log("ERROR", "job_file_download_failed", job_id=job_id, index=index, path=cleaned_path, error=str(e))
                        zip_file.writestr(
                            _safe_output_name(cleaned_path, index),
                            json.dumps({"error": f"Download failed: {e}", "path": cleaned_path}, indent=2, ensure_ascii=False)
                        )
                        continue
                    if not response.ok:
                        _log("ERROR", "job_file_download_bad_response", job_id=job_id, index=index, path=cleaned_path, status=response.status_code, body=(response.text[:200] if response.text else None))
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
                    _log("INFO", "job_file_extract_start", job_id=job_id, index=index, path=cleaned_path, html_len=len(html_text))
                    try:
                        extractor = HTMLToSemanticJSON(html_text)
                        result = extractor.extract()
                        _log("INFO", "job_file_extract_ok", job_id=job_id, index=index, path=cleaned_path)
                    except Exception as exc:
                        _log("ERROR", "job_file_extract_failed", job_id=job_id, index=index, path=cleaned_path, error=str(exc))
                        result = {"error": f"Extraction failed: {exc}"}

                    zip_file.writestr(
                        _safe_output_name(cleaned_path, index),
                        json.dumps(result, indent=2, ensure_ascii=False)
                    )

            zip_size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0
            _log("INFO", "job_zip_done", job_id=job_id, zip_path=zip_path, zip_size_bytes=zip_size)

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
            _log("INFO", "job_upload_start", job_id=job_id, output_path=output_path)
            try:
                with open(zip_path, "rb") as zip_file:
                    upload_response = requests.post(
                        upload_url, headers=upload_headers, data=zip_file, timeout=120
                    )
            except Exception as e:
                _log("ERROR", "job_upload_request_failed", job_id=job_id, error=str(e))
                raise
            if not upload_response.ok:
                _log("ERROR", "job_upload_bad_response", job_id=job_id, status=upload_response.status_code, body=(upload_response.text[:500] if upload_response.text else None))
                raise RuntimeError(upload_response.text)

            _log("INFO", "job_upload_ok", job_id=job_id, output_path=output_path)

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
            _log("INFO", "job_completed", job_id=job_id, output_path=output_path)
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
            tb = traceback.format_exc()
            _log("ERROR", "job_failed", job_id=job_id, error=str(exc), traceback=tb)
            print(f"[worker] Job {job_id} failed: {exc}", flush=True)
            print(tb, flush=True)
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
