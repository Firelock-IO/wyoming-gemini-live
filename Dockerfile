# syntax=docker/dockerfile:1
#
# Wyoming Gemini Live
# - Python 3.13
# - uv for reproducible, fast dependency installs
#
# Build: docker build -t wyoming-gemini-live .
# Run:   docker run --rm -p 10700:10700 --env-file .env wyoming-gemini-live

FROM python:3.13-slim-bookworm AS builder

# uv binary (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy full repo (simplest, avoids edge cases around editable installs)
COPY . .

# Create venv + install deps
RUN uv sync --no-dev

FROM python:3.13-slim-bookworm AS runtime

WORKDIR /app

# Copy the venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source (keeps "python -m" working even without installing the project)
COPY src/ /app/src/
COPY README.md /app/README.md
COPY pyproject.toml /app/pyproject.toml

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

EXPOSE 10700/tcp

CMD ["python", "-m", "wyoming_gemini_live"]
