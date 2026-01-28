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
        background: "#050505",
        color: "#ffffff",
        fontFamily: "Inter, system-ui, sans-serif"
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "28px 40px",
          borderBottom: "1px solid #1a1a1a"
        }}
      >
        <div style={{ fontSize: 14, letterSpacing: "0.24em" }}>SAVAGE</div>
        <img
          src="/logo.png"
          alt="Savage"
          style={{ height: 28, objectFit: "contain" }}
        />
      </header>

      <main style={{ maxWidth: 980, margin: "0 auto", padding: "48px 24px" }}>
        <section style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: 36, marginBottom: 12 }}>
            HTML to Semantic JSON Extractor
          </h1>
          <p style={{ color: "#bdbdbd", maxWidth: 640, lineHeight: 1.6 }}>
            Upload a rendered HTML file to extract structured semantic JSON for
            SEO analysis.
          </p>
        </section>

        <section
          style={{
            background: "#0f0f0f",
            border: "1px solid #1f1f1f",
            borderRadius: 16,
            padding: 28,
            marginBottom: 28
          }}
        >
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 18, marginBottom: 6 }}>Upload HTML</div>
            <div style={{ color: "#9b9b9b", fontSize: 14 }}>
              Select a single rendered HTML file to process.
            </div>
          </div>

          <form onSubmit={handleSubmit} style={{ display: "flex", gap: 16 }}>
            <label
              style={{
                flex: 1,
                background: "#090909",
                border: "1px dashed #2c2c2c",
                padding: "16px 18px",
                borderRadius: 12,
                display: "flex",
                alignItems: "center",
                gap: 12
              }}
            >
              <input
                type="file"
                accept=".html,text/html"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                style={{ color: "#ffffff" }}
              />
              <span style={{ color: "#9b9b9b", fontSize: 13 }}>
                {file ? file.name : "Choose HTML file"}
              </span>
            </label>

            <button
              type="submit"
              disabled={loading}
              style={{
                padding: "14px 22px",
                borderRadius: 12,
                border: "1px solid #ffffff",
                background: loading ? "#222222" : "#ffffff",
                color: loading ? "#bdbdbd" : "#050505",
                fontWeight: 600,
                cursor: loading ? "not-allowed" : "pointer"
              }}
            >
              {loading ? "Processing..." : "Extract JSON"}
            </button>
          </form>
        </section>

        {error && (
          <div
            style={{
              color: "#ff6b6b",
              background: "#1b0b0b",
              border: "1px solid #3a0f0f",
              borderRadius: 12,
              padding: "12px 16px",
              marginBottom: 18
            }}
          >
            {error}
          </div>
        )}

        {result && (
          <section
            style={{
              background: "#0f0f0f",
              border: "1px solid #1f1f1f",
              borderRadius: 16,
              padding: 24
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
              <div style={{ fontSize: 16 }}>Output</div>
              <button
                onClick={downloadJson}
                style={{
                  border: "1px solid #ffffff",
                  background: "transparent",
                  color: "#ffffff",
                  padding: "8px 14px",
                  borderRadius: 10,
                  cursor: "pointer"
                }}
              >
                Download JSON
              </button>
            </div>
            <pre
              style={{
                background: "#080808",
                borderRadius: 12,
                padding: 16,
                maxHeight: 520,
                overflow: "auto",
                whiteSpace: "pre-wrap",
                color: "#eaeaea",
                border: "1px solid #1f1f1f"
              }}
            >
              {result}
            </pre>
          </section>
        )}
      </main>
    </div>
  );
}
