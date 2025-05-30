FROM python:3.11-slim
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Use Digital Ocean's PORT environment variable if set, otherwise default to 4000
ENV PORT=${PORT:-4000}

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:$PORT/health || exit 1

# Expose port
EXPOSE $PORT

# Start the application with dynamic port binding
CMD uvicorn auth:app --host 0.0.0.0 --port $PORT