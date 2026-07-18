# Backend Dockerfile for Railway deployment
FROM python:3.11-slim

# Install system deps (needed by some Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the backend source
COPY . .

# Railway will set $PORT; default to 8001 locally
ENV PORT=8001
EXPOSE 8001

# Run FastAPI with uvicorn (Railway health-checks on $PORT)
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT}
