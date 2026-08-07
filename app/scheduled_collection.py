from __future__ import annotations

import contextlib
import datetime
import logging
import logging.handlers
import os
import time
from pathlib import Path

from . import secure_storage
from .collector import persist_companies, run_daily_income_for_companies
from .income_tracking import reporting_period_start

LOCK_PATH = secure_storage.APP_DATA_DIR / "scheduled_collection.lock"
LOG_PATH = secure_storage.APP_DATA_DIR / "scheduled_collection.log"


def company_is_due(company: dict, timestamp: int) -> bool:
    period = reporting_period_start(timestamp)
    try:
        last = int(company.get("last_scheduled_income_period") or 0)
    except (TypeError, ValueError):
        last = 0
    return bool(period and last < period)


def _configure_logging() -> logging.Logger:
    secure_storage.APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("tca.scheduled_collection")
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=512_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


@contextlib.contextmanager
def collection_lock():
    secure_storage.APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK_PATH, "a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                acquired = False
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                acquired = False
        yield acquired
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _utc_text(timestamp: int) -> str:
    return datetime.datetime.fromtimestamp(
        timestamp, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")


def _collect_with_retries(
    companies: list[dict],
    settings,
    max_attempts: int = 3,
) -> list:
    remaining = list(companies)
    results_by_name = {}
    for attempt in range(max_attempts):
        batch = run_daily_income_for_companies(
            remaining, base_settings=settings
        )
        remaining_by_name = {
            name for name, result in batch if not result.ok
        }
        for name, result in batch:
            results_by_name[name] = result
        if not remaining_by_name:
            break
        remaining = [
            company for company in remaining
            if str(company.get("name") or "Unnamed") in remaining_by_name
        ]
        if attempt + 1 < max_attempts:
            time.sleep(2 ** attempt)
    return [
        (str(company.get("name") or "Unnamed"), results_by_name[str(company.get("name") or "Unnamed")])
        for company in companies
    ]


def run_scheduled_collection(
    companies: list[dict],
    settings,
    timestamp: int | None = None,
    force: bool = False,
    persist: bool = True,
) -> tuple[int, list]:
    now = int(timestamp or time.time())
    logger = _configure_logging()
    if not force and not settings.scheduled_collection_enabled:
        return 0, []

    selected = {
        str(name) for name in (settings.scheduled_company_names or [])
        if str(name).strip()
    }
    scoped = [
        company for company in companies
        if not selected or str(company.get("name", "")) in selected
    ]
    due = [
        company for company in scoped
        if force or company_is_due(company, now)
    ]
    settings.scheduled_last_run = _utc_text(now)
    if not due:
        settings.scheduled_last_result = "Already current for this reporting period."
        settings.save()
        return 0, []

    with collection_lock() as acquired:
        if not acquired:
            settings.scheduled_last_result = "Skipped because another collection is running."
            settings.save()
            logger.info(settings.scheduled_last_result)
            return 0, []

        results = _collect_with_retries(due, settings)
        period = reporting_period_start(now)
        by_name = {
            str(company.get("name") or "Unnamed"): company for company in due
        }
        failures = []
        for name, result in results:
            if result.ok:
                by_name[name]["last_scheduled_income_period"] = period
            else:
                failures.append(f"{name}: {result.message}")
        if persist:
            persist_companies(companies)

        if failures:
            settings.scheduled_last_result = "; ".join(failures)
            exit_code = 1
            logger.error(settings.scheduled_last_result)
        else:
            names = ", ".join(name for name, _result in results)
            settings.scheduled_last_result = f"Updated: {names}"
            exit_code = 0
            logger.info(settings.scheduled_last_result)
        settings.save()
        return exit_code, results
