from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from tca_web.application.contracts import JsonObject
from tca_web.integrations.workbook.xlsx import (
    WorkbookValidationError,
    export_workbook,
    parse_workbook,
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
router = APIRouter(prefix="/local/history", tags=["local-history"])


def _database_dsn() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="Database is not configured")
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _connection() -> Any:
    return await asyncpg.connect(_database_dsn(), timeout=5)


async def _ensure_table(connection: Any) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS portable_history_records (
            workspace_id text NOT NULL,
            company_id bigint NOT NULL,
            record_id text NOT NULL,
            entity_type text NOT NULL,
            payload jsonb NOT NULL,
            imported_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, company_id, record_id)
        )
        """
    )


def _record_id(record: JsonObject) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@router.post("/import")
async def import_history(
    file: UploadFile = File(...),
    workspace_id: str = Query(default="local", min_length=1, max_length=100),
    company_id: int = Query(gt=0),
) -> dict[str, int]:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx workbooks are accepted")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Workbook exceeds the 25 MB limit")
    try:
        records = parse_workbook(content)
    except WorkbookValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    connection = await _connection()
    imported = 0
    try:
        await _ensure_table(connection)
        async with connection.transaction():
            for record in records:
                result = await connection.execute(
                    """
                    INSERT INTO portable_history_records
                        (workspace_id, company_id, record_id, entity_type, payload)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    ON CONFLICT DO NOTHING
                    """,
                    workspace_id,
                    company_id,
                    _record_id(record),
                    str(record.get("_sheet") or "History"),
                    json.dumps(record, default=str),
                )
                imported += int(result.endswith("1"))
    finally:
        await connection.close()
    return {"imported_count": imported, "skipped_count": len(records) - imported}


@router.get("/export")
async def export_history(
    workspace_id: str = Query(default="local", min_length=1, max_length=100),
    company_id: int = Query(gt=0),
) -> Response:
    connection = await _connection()
    try:
        await _ensure_table(connection)
        rows = await connection.fetch(
            """
            SELECT payload
            FROM portable_history_records
            WHERE workspace_id = $1 AND company_id = $2
            ORDER BY entity_type, record_id
            """,
            workspace_id,
            company_id,
        )
    finally:
        await connection.close()
    records = [
        dict(row["payload"])
        if isinstance(row["payload"], dict)
        else json.loads(str(row["payload"]))
        for row in rows
    ]
    content = export_workbook(records, workspace_id=workspace_id, company_id=company_id)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="tca-company-{company_id}-history.xlsx"'
        },
    )
