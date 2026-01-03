FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Default port
ENV PORT=8080

# Worker service (Pub/Sub push handler)
CMD ["python", "-m", "uvicorn", "src.indexing.push_app:app", "--host", "0.0.0.0", "--port", "8080"]


