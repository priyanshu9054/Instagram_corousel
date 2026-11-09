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
# Scratch dir for runtime state (strategy, content log, IG session). No volume is
# mounted here on purpose: this state is ephemeral and gets recovered through the API
# after a redeploy (see server.py's /session/upload and /state/rebuild).
ENV DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000

CMD ["python", "main.py"]
