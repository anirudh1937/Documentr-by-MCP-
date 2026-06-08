FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy packaging files
COPY pyproject.toml README.md ./

# Install python dependencies
RUN pip install --no-cache-dir .

# Copy source code and static assets
COPY src/ ./src/
COPY static/ ./static/
COPY main.py ./

# Pre-create data directories
RUN mkdir -p /app/documents /app/agent_state

# Expose server port
EXPOSE 8765

# Set env configurations
ENV PORT=8765
ENV PYTHONUNBUFFERED=1

# Start FastAPI web server
CMD ["python", "main.py", "web"]
