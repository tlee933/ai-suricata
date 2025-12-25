# AI Suricata - Intelligent Threat Detection & Response
# Multi-stage build for smaller final image

FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --user -r /tmp/requirements.txt

# Final stage
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local

# Set PATH for user-installed packages
ENV PATH=/root/.local/bin:$PATH

# Create working directory
WORKDIR /app

# Copy application files
COPY *.py ./
COPY config.env ./

# Create directories for data (will be mounted as volumes)
RUN mkdir -p /app/state /app/logs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import http.client; \
                    conn = http.client.HTTPConnection('localhost', 8000); \
                    conn.request('GET', '/'); \
                    r = conn.getresponse(); \
                    exit(0 if r.status == 200 else 1)" || exit 1

# Expose Prometheus metrics port
EXPOSE 8000

# Run AI Suricata
ENTRYPOINT ["python3", "ai_suricata.py"]
CMD ["--train", "--auto-block", "--events", "3000"]
