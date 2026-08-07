from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tca_web.application.contracts import (
    Operation,
    ProgressEvent,
    ProgressState,
    emit_progress,
)


def event() -> ProgressEvent:
    return ProgressEvent(
        operation=Operation.SNAPSHOT,
        stage="employees",
        state=ProgressState.RUNNING,
        message="Fetching employees",
        current=1,
        total=3,
        occurred_at=datetime(2026, 8, 7, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_emit_progress_supports_sync_and_async_callbacks() -> None:
    received: list[ProgressEvent] = []

    async def async_callback(progress: ProgressEvent) -> None:
        received.append(progress)

    await emit_progress(received.append, event())
    await emit_progress(async_callback, event())

    assert received == [event(), event()]


def test_progress_requires_complete_valid_counts() -> None:
    with pytest.raises(ValidationError, match="supplied together"):
        ProgressEvent(
            operation=Operation.SNAPSHOT,
            stage="employees",
            state=ProgressState.RUNNING,
            message="Fetching employees",
            current=1,
        )

    with pytest.raises(ValidationError, match="cannot exceed"):
        ProgressEvent(
            operation=Operation.SNAPSHOT,
            stage="employees",
            state=ProgressState.RUNNING,
            message="Fetching employees",
            current=4,
            total=3,
        )
