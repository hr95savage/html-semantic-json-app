import { useState } from "react";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setResult("");

    if (!file) {
      setError("Please select an HTML file to upload.");
      return;
    }

    setLoading(true);
    try {
      const htmlText = await file.text();
      const response = await fetch("/api/extract", {
        method: "POST",
        headers: {
          "Content-Type": "text/html; charset=utf-8"
        },
        body: htmlText
      });

      const responseText = await response.text();
      if (!response.ok) {
        setError(`Extraction failed: ${responseText}`);
        return;
      }

      setResult(responseText);
    } catch (err) {
      setError(`Unexpected error: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  const downloadJson = () => {
    if (!result) {
      return;
    }
    const blob = new Blob([result], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "semantic_output.json";
    link.click();
    URL.revokeObjectURL(url);
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
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
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
                  cursor: "pointer"
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
                  {file ? file.name : "Choose a rendered HTML file"}
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
                opacity: loading ? 0.6 : 1
              }}
            >
              {loading ? "Processing..." : "Extract JSON"}
            </button>
          </form>

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

          {result && (
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
                  Output
                </span>
                <button
                  onClick={downloadJson}
                  style={{
                    padding: "10px 20px",
                    background: "#262626",
                    color: "#ffffff",
                    border: "1px solid #404040",
                    borderRadius: 8,
                    fontSize: "0.875rem",
                    fontWeight: 500,
                    cursor: "pointer"
                  }}
                >
                  Download JSON
                </button>
              </div>
              <pre
                style={{
                  background: "#0a0a0a",
                  color: "#a3a3a3",
                  padding: 14,
                  borderRadius: 6,
                  fontFamily: "ui-monospace, monospace",
                  fontSize: "0.8rem",
                  maxHeight: 220,
                  overflowY: "auto",
                  border: "1px solid #1f1f1f",
                  whiteSpace: "pre-wrap"
                }}
              >
                {result}
              </pre>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
