FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Recife

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

COPY main.py index.html .

USER app

EXPOSE 4100

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4100"]
