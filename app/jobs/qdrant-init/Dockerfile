# Qdrant Initialization Job
# Downloads IMDB data from Azure Blob Storage and indexes into Qdrant

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model to speed up job execution
RUN python -c "from sentence_transformers import SentenceTransformer; import mlflow; print('All dependencies installed successfully')"

# Copy application code
COPY main.py .

# Run as non-root user
RUN useradd -m -u 1000 appuser
USER appuser

CMD ["python", "main.py"]
