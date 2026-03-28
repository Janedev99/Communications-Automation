FROM python:3.12-slim

# System deps needed by psycopg2-binary and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 8000

# Default command — docker-compose overrides this with alembic + uvicorn chain
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
