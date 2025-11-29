FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Устанавливаем зависимости системы
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# EXPOSE в Railway носит информативный характер, но оставим его
EXPOSE 8000

# ВАЖНЫЕ ИЗМЕНЕНИЯ В CMD:
# 1. Мы убрали квадратные скобки ["..."], чтобы использовать shell-режим.
#    Это позволяет автоматически подставить переменную $PORT.
# 2. Мы заменили фиксированный порт 8000 на $PORT (требование Railway).
# 3. Мы используем полный путь к python -m, но лучше просто вызвать бинарник alembic.

CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT