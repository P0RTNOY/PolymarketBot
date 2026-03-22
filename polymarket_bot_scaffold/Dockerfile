# Base image for all services (shared, avoids re-downloading python:3.12-slim per service)
FROM python:3.12-slim

WORKDIR /app

# System deps (no gcc needed for pure-python stack)
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install project dependencies only (layer-cached unless pyproject.toml changes)
COPY pyproject.toml .
COPY README.md .
RUN pip install --no-cache-dir -e . 2>/dev/null || true

# Copy full source (mounted at runtime anyway, but baked in for image portability)
COPY . .

# Final install in case editable install missed something
RUN pip install --no-cache-dir -e .
