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
    <main style={{ maxWidth: 900, margin: "40px auto", padding: 24 }}>
      <h1 style={{ fontSize: 28, marginBottom: 8 }}>
        HTML to Semantic JSON Extractor
      </h1>
      <p style={{ marginBottom: 24 }}>
        Upload a rendered HTML file to extract semantic JSON.
      </p>

      <form onSubmit={handleSubmit} style={{ marginBottom: 24 }}>
        <input
          type="file"
          accept=".html,text/html"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <button
          type="submit"
          style={{ marginLeft: 12 }}
          disabled={loading}
        >
          {loading ? "Extracting..." : "Extract JSON"}
        </button>
      </form>

      {error && (
        <div style={{ color: "#b00020", marginBottom: 16 }}>{error}</div>
      )}

      {result && (
        <>
          <button onClick={downloadJson} style={{ marginBottom: 12 }}>
            Download JSON
          </button>
          <pre
            style={{
              background: "#f5f5f5",
              padding: 16,
              borderRadius: 6,
              maxHeight: 520,
              overflow: "auto",
              whiteSpace: "pre-wrap"
            }}
          >
            {result}
          </pre>
        </>
      )}
    </main>
  );
}
