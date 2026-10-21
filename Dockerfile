FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
RUN mkdir -p /app/observation-data && chown appuser:appuser /app/observation-data
COPY --from=builder /opt/venv /opt/venv
COPY src ./src
COPY web ./web
COPY models/wildfire_real.joblib ./models/wildfire_real.joblib
COPY reports/real_metrics.json ./reports/real_metrics.json

USER appuser
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os; from urllib.request import urlopen; urlopen('http://127.0.0.1:' + os.environ.get('PORT', '7860') + '/health', timeout=3)"

CMD ["sh", "-c", "exec uvicorn src.wildfire.api:app --host 0.0.0.0 --port ${PORT:-7860}"]
