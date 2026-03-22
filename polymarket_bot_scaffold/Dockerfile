FROM python:3.12-slim

# Install curl (needed for the API health-check) and basic OS deps
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifest first (layer cache friendly)
COPY pyproject.toml ./
COPY README.md ./

# Install project in editable mode so all workers see bot.* imports
RUN pip install --no-cache-dir -e .

# Copy source (the volume mount in docker-compose will overlay this at runtime,
# but we still copy so the image is self-contained for other environments)
COPY . .

# Default: override in compose command
CMD ["python", "--version"]
