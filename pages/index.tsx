import { useState } from "react";

export default function Home() {
  const [files, setFiles] = useState<File[]>([]);
  const [downloadUrl, setDownloadUrl] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [uploadedCount, setUploadedCount] = useState(0);
  const apiBase = process.env.NEXT_PUBLIC_API_BASE || "";

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setDownloadUrl("");
    setStatus("");
    setUploadedCount(0);

    if (!files.length) {
      setError("Please select one or more HTML files to upload.");
      return;
    }

    setLoading(true);
    try {
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

      const signPayload = await signResponse.json();
      if (!signResponse.ok) {
        setError(
          `Upload signing failed: ${signPayload?.error || signResponse.statusText}`
        );
        return;
      }

      const uploads = signPayload?.uploads ?? [];
      if (!uploads.length) {
        setError("No signed uploads returned from the server.");
        return;
      }

      for (let index = 0; index < uploads.length; index += 1) {
        const upload = uploads[index];
        const file = files[index];
        setStatus(`Uploading ${index + 1} of ${uploads.length}...`);
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
          setError(`Upload failed: ${errorText || uploadResponse.statusText}`);
          return;
        }
      }

      setStatus("Processing files...");
      const processResponse = await fetch(`${apiBase}/api/supabase/process`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          paths: uploads.map((upload: { path: string }) => upload.path)
        })
      });
      const processPayload = await processResponse.json();
      if (!processResponse.ok) {
        setError(
          `Processing failed: ${
            processPayload?.error || processResponse.statusText
          }`
        );
        return;
      }

      if (processPayload?.downloadUrl) {
        setDownloadUrl(encodeURI(processPayload.downloadUrl));
        setStatus("Ready to download.");
      } else {
        setError("Processing completed, but no download URL was returned.");
      }
    } catch (err) {
      setError(`Unexpected error: ${err}`);
    } finally {
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
                padding: 14,
                background: "#0a0a0a",
                border: "1px solid #262626",
                borderRadius: 8,
                color: "#a3a3a3",
                fontWeight: 500
              }}
            >
              {status}
              {uploadedCount > 0 && (
                <span style={{ marginLeft: 8 }}>
                  ({uploadedCount}/{files.length})
                </span>
              )}
            </div>
          )}

          {error && (
            <div
              style={{
                marginTop: 20,
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
