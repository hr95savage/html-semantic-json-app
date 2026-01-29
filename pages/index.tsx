import { useRef, useState } from "react";

type Phase = "idle" | "uploading" | "processing" | "done" | "error";

export default function Home() {
  const [files, setFiles] = useState<File[]>([]);
  const [downloadUrl, setDownloadUrl] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [uploadedCount, setUploadedCount] = useState(0);
  const [jobId, setJobId] = useState<string>("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [currentExtractingFileIndex, setCurrentExtractingFileIndex] = useState(0);
  const apiBase = process.env.NEXT_PUBLIC_API_BASE || "";

  const canLogDebug =
    typeof window !== "undefined" && window.location.hostname === "localhost";

  const pollStartRef = useRef<number | null>(null);
  const processingStepIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const POLL_TIMEOUT_MS = 60 * 60 * 1000; // 1 hour (large files can be slow)
  const EXTRACT_STEP_SECONDS = 8; // advance to next file every N seconds (estimate)

  const stopProcessingStep = () => {
    if (processingStepIntervalRef.current) {
      clearInterval(processingStepIntervalRef.current);
      processingStepIntervalRef.current = null;
    }
    setCurrentExtractingFileIndex(0);
  };

  const startProcessingStep = (totalFiles: number) => {
    stopProcessingStep();
    setCurrentExtractingFileIndex(0);
    processingStepIntervalRef.current = setInterval(() => {
      setCurrentExtractingFileIndex((i) => Math.min(i + 1, totalFiles - 1));
    }, EXTRACT_STEP_SECONDS * 1000);
  };

  const pollJobStatus = async (jobId: string) => {
    pollStartRef.current = Date.now();
    const poll = async () => {
      if (
        pollStartRef.current !== null &&
        Date.now() - pollStartRef.current > POLL_TIMEOUT_MS
      ) {
        stopProcessingStep();
        setPhase("error");
        setError(
          "Processing is taking longer than usual. The job may still be running — try \"Check status again\" below, or upload again if needed."
        );
        setLoading(false);
        pollStartRef.current = null;
        return;
      }
      const response = await fetch(
        `${apiBase}/api/jobs?job_id=${encodeURIComponent(jobId)}`
      );
      const text = await response.text();
      // #region agent log
      if (canLogDebug) {
        fetch("http://127.0.0.1:7243/ingest/f6d307e4-5b0c-4cc3-9b40-1f63f1b83f10", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            location: "pages/index.tsx:18",
            message: "job_status",
            data: { status: response.status, length: text.length },
            timestamp: Date.now(),
            sessionId: "debug-session",
            runId: "run1",
            hypothesisId: "H8"
          })
        }).catch(() => {});
      }
      // #endregion
      let payload: { status?: string; downloadUrl?: string; error?: string } | null = null;
      try {
        payload = text ? JSON.parse(text) : null;
      } catch {
        payload = null;
      }
      if (!response.ok) {
        stopProcessingStep();
        pollStartRef.current = null;
        setPhase("error");
        setError(`Job check failed: ${payload?.error || text || response.statusText}`);
        setLoading(false);
        return;
      }

      if (payload?.status === "completed" && payload.downloadUrl) {
        stopProcessingStep();
        pollStartRef.current = null;
        setPhase("done");
        setDownloadUrl(encodeURI(payload.downloadUrl));
        setStatus("Ready to download.");
        setLoading(false);
        return;
      }

      if (payload?.status === "failed") {
        stopProcessingStep();
        pollStartRef.current = null;
        setPhase("error");
        setError(payload.error || "Processing failed.");
        setLoading(false);
        return;
      }

      setStatus(`Extracting... (job ${jobId.slice(0, 8)})`);
      setTimeout(poll, 5000);
    };

    poll();
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setDownloadUrl("");
    setStatus("");
    setUploadedCount(0);
    setJobId("");
    setPhase("idle");
    setCurrentExtractingFileIndex(0);

    if (!files.length) {
      setError("Please select one or more HTML files to upload.");
      return;
    }

    setLoading(true);
    try {
      setPhase("uploading");
      setStatus("Requesting upload URLs...");
      const signResponse = await fetch(`${apiBase}/api/supabase/sign`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          files: files.map((file) => ({
            name: file.name,
            contentType: file.type || "text/html"
          }))
        })
      });

      const signText = await signResponse.text();
      // #region agent log
      if (canLogDebug) {
        fetch("http://127.0.0.1:7243/ingest/f6d307e4-5b0c-4cc3-9b40-1f63f1b83f10", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            location: "pages/index.tsx:40",
            message: "sign_response",
            data: { status: signResponse.status, length: signText.length },
            timestamp: Date.now(),
            sessionId: "debug-session",
            runId: "run1",
            hypothesisId: "H1"
          })
        }).catch(() => {});
      }
      // #endregion
      let signPayload: { uploads?: Array<{ path: string; signedUrl: string; contentType?: string }>; error?: string } | null = null;
      try {
        signPayload = signText ? JSON.parse(signText) : null;
      } catch {
        signPayload = null;
      }
      if (!signResponse.ok) {
        setPhase("error");
        setError(
          `Upload signing failed: ${signPayload?.error || signText || signResponse.statusText}`
        );
        setLoading(false);
        return;
      }

      const uploads = signPayload?.uploads ?? [];
      if (!uploads.length) {
        setPhase("error");
        setError("No signed uploads returned from the server.");
        setLoading(false);
        return;
      }

      for (let index = 0; index < uploads.length; index += 1) {
        const upload = uploads[index];
        const file = files[index];
        setStatus(`Uploading ${file.name} (${index + 1} of ${uploads.length})`);
        setUploadedCount(index + 1);
        const uploadUrl = encodeURI(upload.signedUrl);
        const uploadResponse = await fetch(uploadUrl, {
          method: "PUT",
          headers: {
            "Content-Type": upload.contentType || file.type || "text/html"
          },
          body: file
        });
        if (!uploadResponse.ok) {
          const errorText = await uploadResponse.text();
          setPhase("error");
          setError(`Upload failed: ${errorText || uploadResponse.statusText}`);
          setLoading(false);
          return;
        }
      }

      setPhase("processing");
      setStatus("Queuing job...");
      const processResponse = await fetch(`${apiBase}/api/supabase/process`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          paths: uploads.map((upload: { path: string }) => upload.path)
        })
      });
      const processText = await processResponse.text();
      // #region agent log
      if (canLogDebug) {
        fetch("http://127.0.0.1:7243/ingest/f6d307e4-5b0c-4cc3-9b40-1f63f1b83f10", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            location: "pages/index.tsx:90",
            message: "process_response",
            data: { status: processResponse.status, length: processText.length },
            timestamp: Date.now(),
            sessionId: "debug-session",
            runId: "run1",
            hypothesisId: "H2"
          })
        }).catch(() => {});
      }
      // #endregion
      let processPayload: { jobId?: string; status?: string; error?: string } | null = null;
      try {
        processPayload = processText ? JSON.parse(processText) : null;
      } catch {
        processPayload = null;
      }
      if (!processResponse.ok) {
        setPhase("error");
        setError(
          `Processing failed: ${
            processPayload?.error || processText || processResponse.statusText
          }`
        );
        setLoading(false);
        return;
      }

      if (processPayload?.jobId) {
        setJobId(processPayload.jobId);
        setStatus("Extracting semantic JSON from your files...");
        startProcessingStep(files.length);
        pollJobStatus(processPayload.jobId);
        return;
      }

      setPhase("error");
      setError("Processing started, but no job ID was returned.");
      setLoading(false);
    } catch (err) {
      setPhase("error");
      setError(`Unexpected error: ${err}`);
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0a0a0a",
        color: "#e5e5e5",
        fontFamily:
          "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
      }}
    >
      <header
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          height: 72,
          background: "#0a0a0a",
          borderBottom: "1px solid #1f1f1f",
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-start",
          padding: "0 24px",
          zIndex: 100
        }}
      >
        <img
          src="/logo.png"
          alt="Savage"
          style={{ height: 112, width: "auto", display: "block" }}
        />
      </header>

      <main
        style={{
          paddingTop: 72,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 0"
        }}
      >
        <div
          style={{
            background: "#141414",
            border: "1px solid #262626",
            borderRadius: 20,
            padding: 48,
            maxWidth: 560,
            width: "100%"
          }}
        >
          <h1
            style={{
              color: "#ffffff",
              marginBottom: 8,
              fontSize: "1.5rem",
              fontWeight: 600
            }}
          >
            HTML to Semantic JSON Extractor
          </h1>
          <p style={{ color: "#a3a3a3", marginBottom: 28, fontSize: "0.9rem" }}>
            Upload a rendered HTML file to extract semantic JSON.
          </p>

          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 24 }}>
              <label
                style={{
                  display: "block",
                  marginBottom: 8,
                  color: "#d4d4d4",
                  fontWeight: 500,
                  fontSize: "0.875rem"
                }}
              >
                HTML File
              </label>
              <input
                id="html-file"
                type="file"
                accept=".html,text/html"
                multiple
                onChange={(event) =>
                  setFiles(Array.from(event.target.files ?? []))
                }
                style={{ display: "none" }}
              />
              <label
                htmlFor="html-file"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 16,
                  width: "100%",
                  padding: "12px 14px",
                  background: "#0a0a0a",
                  border: "1px solid #333",
                  borderRadius: 8,
                  cursor: "pointer",
                  boxSizing: "border-box"
                }}
              >
                <span
                  style={{
                    color: "#a3a3a3",
                    fontSize: "0.9rem",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap"
                  }}
                >
                  {files.length
                    ? files.length === 1
                      ? files[0].name
                      : "Multiple HTML files selected"
                    : "Choose rendered HTML files"}
                </span>
                <span
                  style={{
                    color: "#a3a3a3",
                    fontSize: "0.8rem",
                    marginLeft: 12,
                    flexShrink: 0
                  }}
                >
                  {files.length
                    ? `${files.length} file${files.length === 1 ? "" : "s"}`
                    : ""}
                </span>
                <span
                  style={{
                    padding: "8px 12px",
                    background: "#262626",
                    border: "1px solid #404040",
                    borderRadius: 8,
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    color: "#ffffff",
                    whiteSpace: "nowrap"
                  }}
                >
                  Browse
                </span>
              </label>
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                width: "100%",
                padding: "14px",
                background: "#ffffff",
                color: "#0a0a0a",
                border: "none",
                borderRadius: 8,
                fontSize: "0.95rem",
                fontWeight: 600,
                cursor: loading ? "not-allowed" : "pointer",
                opacity: loading ? 0.6 : 1,
                boxSizing: "border-box"
              }}
            >
              {loading ? "Processing..." : "Upload & Extract"}
            </button>
          </form>

          {status && !error && (
            <div
              style={{
                marginTop: 20,
                padding: 18,
                background: "#0a0a0a",
                border: "1px solid #262626",
                borderRadius: 8
              }}
            >
              <div style={{ color: "#a3a3a3", fontWeight: 500, marginBottom: 12 }}>
                {status}
              </div>
              {(phase === "uploading" || phase === "processing") && files.length > 0 && (
                <>
                  <div
                    style={{
                      height: 8,
                      background: "#262626",
                      borderRadius: 4,
                      overflow: "hidden",
                      marginBottom: 12
                    }}
                  >
                    <div
                      style={{
                        height: "100%",
                        width:
                          phase === "uploading"
                            ? `${(uploadedCount / files.length) * 100}%`
                            : phase === "processing"
                              ? `${((currentExtractingFileIndex + 1) / files.length) * 100}%`
                              : "0%",
                        background: "#ffffff",
                        borderRadius: 4,
                        transition: "width 0.3s ease"
                      }}
                    />
                  </div>
                  <div style={{ fontSize: "0.8rem", color: "#737373" }}>
                    {phase === "uploading"
                      ? `Uploaded ${uploadedCount} of ${files.length} file(s)`
                      : phase === "processing"
                        ? `Extracting file ${currentExtractingFileIndex + 1} of ${files.length}: ${files[currentExtractingFileIndex]?.name ?? "—"}`
                        : `Extracting ${files.length} file(s)...`}
                  </div>
                  {phase === "processing" &&
                    files.length > 0 &&
                    currentExtractingFileIndex === files.length - 1 && (
                      <div
                        style={{
                          fontSize: "0.75rem",
                          color: "#525252",
                          marginTop: 6
                        }}
                      >
                        Finishing up — large files can take 1–2 minutes. Still
                        checking for your download…
                      </div>
                    )}
                  {files.length > 0 && (
                    <ul
                      style={{
                        marginTop: 10,
                        marginBottom: 0,
                        paddingLeft: 20,
                        fontSize: "0.8rem",
                        color: "#525252",
                        maxHeight: 120,
                        overflowY: "auto"
                      }}
                    >
                      {files.map((f, i) => (
                        <li
                          key={i}
                          style={{
                            marginBottom: 4,
                            color:
                              phase === "processing" &&
                              currentExtractingFileIndex === i
                                ? "#e5e5e5"
                                : "#525252"
                          }}
                        >
                          {phase === "processing" &&
                            currentExtractingFileIndex === i && (
                              <span style={{ marginRight: 6 }}>●</span>
                            )}
                          {f.name}
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          )}

          {error && (
            <div style={{ marginTop: 20 }}>
              <div
                style={{
                  padding: 14,
                  background: "#0a0a0a",
                  border: "1px solid #262626",
                  borderRadius: 8,
                  color: "#ef4444",
                  fontWeight: 600
                }}
              >
                {error}
              </div>
              {jobId && (
                <button
                  type="button"
                  onClick={() => {
                    setError("");
                    setLoading(true);
                    setPhase("processing");
                    setStatus("Checking job status...");
                    if (files.length > 0) startProcessingStep(files.length);
                    pollJobStatus(jobId);
                  }}
                  style={{
                    marginTop: 10,
                    padding: "10px 16px",
                    background: "#262626",
                    color: "#e5e5e5",
                    border: "1px solid #404040",
                    borderRadius: 8,
                    fontSize: "0.875rem",
                    fontWeight: 500,
                    cursor: "pointer"
                  }}
                >
                  Check status again
                </button>
              )}
            </div>
          )}

          {downloadUrl && (
            <div
              style={{
                marginTop: 28,
                padding: 20,
                background: "#0a0a0a",
                border: "1px solid #262626",
                borderRadius: 8
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 12
                }}
              >
                <span style={{ fontWeight: 600, color: "#a3a3a3" }}>
                  Output ZIP
                </span>
                <a
                  href={downloadUrl}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    padding: "10px 20px",
                    background: "#262626",
                    color: "#ffffff",
                    border: "1px solid #404040",
                    borderRadius: 8,
                    fontSize: "0.875rem",
                    fontWeight: 500,
                    cursor: "pointer",
                    textDecoration: "none"
                  }}
                >
                  Download ZIP
                </a>
              </div>
              <p style={{ margin: 0, color: "#737373", fontSize: "0.85rem" }}>
                Your JSON outputs are zipped and ready to download.
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
