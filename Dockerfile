# syntax=docker/dockerfile:1

# ---- Builder: resolve and install dependencies into a venv ----
FROM python:3.12-slim AS builder

# uv for fast, reproducible installs (pinned by tag for repeatable builds)
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cached layer) using only the lockfiles.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Then install the project itself.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- Runtime: slim image with just the venv and source ----
FROM python:3.12-slim AS runtime

# Non-root service user with a fixed uid.
RUN useradd --system --uid 10001 --create-home --home-dir /home/vboard vboard

WORKDIR /app

# Copy the built venv and source, owned by the service user.
COPY --from=builder --chown=vboard:vboard /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    VBOARD_CONFIG=/data/config.json \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Shared config lives on a volume so both containers (UI + scheduler) see the same file.
RUN mkdir -p /data && chown vboard:vboard /data
VOLUME ["/data"]

USER vboard

EXPOSE 8501

# Default role is the UI; the scheduler service overrides the command in compose.
# Binding 0.0.0.0 is in-container only — the host publishes the port to 127.0.0.1.
CMD ["streamlit", "run", "src/vboard/ui/app.py", \
     "--server.address", "0.0.0.0", \
     "--server.port", "8501", \
     "--server.headless", "true"]
