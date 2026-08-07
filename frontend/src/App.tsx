import { type FormEvent, useState } from "react";
import { Route, Routes } from "react-router";

import "./App.css";

function HomePage() {
  const [companyId, setCompanyId] = useState("1");
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("");

  async function importHistory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setStatus("Importing workbook...");
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(
      `/api/local/history/import?workspace_id=local&company_id=${companyId}`,
      { method: "POST", body },
    );
    if (!response.ok) {
      const error = (await response.json()) as { detail?: string };
      setStatus(error.detail ?? "Import failed.");
      return;
    }
    const result = (await response.json()) as {
      imported_count: number;
      skipped_count: number;
    };
    setStatus(
      `Imported ${result.imported_count}; skipped ${result.skipped_count} duplicate records.`,
    );
  }

  return (
    <main className="app-shell">
      <section className="app-card">
        <p className="eyebrow">Web migration initialized</p>
        <h1>Torn Company Assistant</h1>
        <p>
          FastAPI, React, PostgreSQL, and background-job foundations are ready.
        </p>
        <div className="local-tools">
          <h2>Local history workbook</h2>
          <p>Import or export portable company history without Google Drive.</p>
          <form onSubmit={importHistory}>
            <label>
              Company ID
              <input
                min="1"
                required
                type="number"
                value={companyId}
                onChange={(event) => setCompanyId(event.target.value)}
              />
            </label>
            <label>
              History workbook
              <input
                accept=".xlsx"
                required
                type="file"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <button type="submit">Import history</button>
            <a
              className="button-link"
              href={`/api/local/history/export?workspace_id=local&company_id=${companyId}`}
            >
              Export history
            </a>
          </form>
          {status && <p role="status">{status}</p>}
        </div>
      </section>
    </main>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="*" element={<HomePage />} />
    </Routes>
  );
}

export default App;
