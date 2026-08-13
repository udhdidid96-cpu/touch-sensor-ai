# Production Dockerfile for Permanent Cloud Deployment (Render, HuggingFace, Koyeb, Railway)
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specifications
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Run Master Engine on 0.0.0.0 reading dynamic PORT from environment
CMD ["python", "main.py", "--host", "0.0.0.0"]
