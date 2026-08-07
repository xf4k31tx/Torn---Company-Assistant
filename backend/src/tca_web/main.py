import asyncio
import os

import asyncpg  # type: ignore[import-untyped]
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from tca_web.local_history import router as local_history_router

app = FastAPI(title="Torn Company Assistant", version="0.1.0")
app.include_router(local_history_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _postgres_ready(database_url: str) -> bool:
    connection: asyncpg.Connection[asyncpg.Record] | None = None
    try:
        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        connection = await asyncpg.connect(dsn, timeout=3)
        return bool(await connection.fetchval("SELECT 1"))
    except (OSError, asyncpg.PostgresError, TimeoutError):
        return False
    finally:
        if connection is not None:
            await connection.close()


async def _redis_ready(redis_url: str) -> bool:
    client = Redis.from_url(redis_url)
    try:
        return bool(await client.ping())
    except (OSError, TimeoutError):
        return False
    finally:
        await client.aclose()


@app.get("/ready", tags=["system"], response_model=None)
async def ready() -> JSONResponse:
    database_url = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL")
    if not database_url or not redis_url:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "postgres": False, "redis": False},
        )
    postgres, redis = await asyncio.gather(
        _postgres_ready(database_url),
        _redis_ready(redis_url),
    )
    status_code = 200 if postgres and redis else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if status_code == 200 else "not_ready",
            "postgres": postgres,
            "redis": redis,
        },
    )
