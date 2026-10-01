# DriveNow API and worker image (the worker overrides the command).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install .

# Run as a non-root user. /app/logs is created here and owned by that user,
# so a named volume mounted on it starts with the same ownership.
RUN useradd --system --uid 10001 --no-create-home drivenow \
    && mkdir -p /app/logs \
    && chown drivenow:drivenow /app/logs
USER drivenow

ENV API_HOST=0.0.0.0 \
    API_PORT=8000 \
    LOG_FILE=/app/logs/drivenow.log \
    WORKER_LOG_FILE=/app/logs/worker.log

EXPOSE 8000
CMD ["python", "-m", "drivenow"]
