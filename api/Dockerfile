FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin fos

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

RUN mkdir -p /app/uploads && chown -R fos:fos /app/uploads

USER fos

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
