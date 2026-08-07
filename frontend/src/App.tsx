import { Route, Routes } from "react-router";

import "./App.css";

function HomePage() {
  return (
    <main className="app-shell">
      <section className="app-card">
        <p className="eyebrow">Web migration initialized</p>
        <h1>Torn Company Assistant</h1>
        <p>
          FastAPI, React, PostgreSQL, and background-job foundations are ready.
        </p>
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
