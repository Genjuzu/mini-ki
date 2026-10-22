# Mini-KI. Gewichte werden hier nicht geladen und nicht kopiert.
# Sie gehören ins Volume /data/modell-cache, sobald die lokale Einbettung läuft.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip install --no-cache-dir /app \
    && rm -rf /root/.cache \
    && useradd --system --uid 10001 --home-dir /home/mini --create-home mini \
    && mkdir -p /data/modell-cache /data/mandanten/standard/anhaenge \
    && chown -R mini:mini /data

USER mini

VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/v1/gesundheit', timeout=3)"]

CMD ["python", "-m", "mini_ki"]
