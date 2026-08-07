# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml uv.lock ./

FROM base AS development
RUN uv sync --locked --all-groups --no-install-project
COPY src ./src
RUN uv sync --locked --all-groups
CMD ["fastapi", "dev", "--host", "0.0.0.0", "--port", "8000", "src/tca_web/main.py"]

FROM base AS production
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev
RUN useradd --create-home --uid 10001 tca
USER tca
CMD ["fastapi", "run", "--host", "0.0.0.0", "--port", "8000", "src/tca_web/main.py"]
