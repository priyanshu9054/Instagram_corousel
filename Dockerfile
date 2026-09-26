FROM python:3.12-slim

WORKDIR /app

# System build tools: most deps ship prebuilt wheels, but this keeps the build from
# breaking if pip ever needs to compile something (e.g. a pydantic-core bump).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
# Durable state (strategy, content log, IG session) — mount a volume here so it
# survives container restarts/redeploys instead of living in requirements.txt.
ENV DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
