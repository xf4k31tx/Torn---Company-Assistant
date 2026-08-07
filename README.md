# Torn Company Assistant (Web)

PostgreSQL-backed web migration of Torn Company Assistant. The web application uses FastAPI, React, background workers, and local `.xlsx` history import/export without Google integration.

## Repository layout

- `backend/` — FastAPI API, PostgreSQL persistence, Celery workers, and spreadsheet services.
- `frontend/` — React, TypeScript, and Vite browser application.
- `docs/` — architecture decisions and the migration roadmap.

## Local prerequisites

- Python 3.13 managed through `uv`
- Node.js and npm
- Docker Desktop with Docker Compose

## Bootstrap

```powershell
cd backend
uv sync
uv run fastapi dev src/tca_web/main.py
```

```powershell
cd frontend
npm install
npm run dev
```

The Docker Compose development launcher will be added in the local-environment phase.
