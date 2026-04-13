FROM python:3.11-slim

WORKDIR /app

# System dependencies + Node.js 20 LTS (for npx jest test execution)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create working directories
RUN mkdir -p generated_code logs chroma_db

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
