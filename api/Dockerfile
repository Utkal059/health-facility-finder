# API image. Also used by docker compose's `seed` step (migrations + snapshot
# load), which is why db/ and scraper/ are copied in; the browser-driven crawl
# itself is never run from this image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY db ./db
COPY scraper ./scraper
COPY api ./api

# The seed step writes its run report to /app/reports.
RUN useradd --create-home appuser \
    && mkdir -p /app/reports \
    && chown appuser /app/reports
USER appuser

EXPOSE 8000
# Render, Railway and Fly set $PORT; locally it falls back to 8000.
CMD ["sh", "-c", "uvicorn api.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
