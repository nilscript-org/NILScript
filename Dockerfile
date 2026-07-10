FROM python:3.12-slim

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY . /app/

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"

# Expose port
EXPOSE 8000

# Run Control Plane
CMD ["uvicorn", "nilscript.controlplane.app:app", "--host", "0.0.0.0", "--port", "8000"]
