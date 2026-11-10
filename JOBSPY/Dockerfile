FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --shell /usr/sbin/nologin app

COPY main.py .

USER app

EXPOSE 4000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4000"]
