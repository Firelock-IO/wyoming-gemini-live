# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

WORKDIR /app

# Copy all files
COPY . .

# Install build tools (needed for numpy/scipy if wheels miss)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install directly using pip (simpler than uv for HA add-ons)
# This installs dependencies from pyproject.toml
RUN pip install --no-cache-dir .

EXPOSE 10700

CMD ["python3", "-m", "wyoming_gemini_live"]
