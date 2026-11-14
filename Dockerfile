FROM python:3.11-slim

WORKDIR /app

# System dependencies for git operations
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Persistent volumes for data, logs, and the target repository
VOLUME ["/app/database", "/app/logs", "/repo"]

# FastAPI
EXPOSE 8000

ENV PYTHONUNBUFFERED=1

# Default: start the API server
# Override CMD to run CLI mode or tests via docker-compose
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
