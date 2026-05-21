# Interior Copilot API — Google Cloud Run
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

# Cloud Run sets PORT; default 8080 for local docker run
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}
