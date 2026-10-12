FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cohort cohort
COPY catalog catalog
COPY eval eval
COPY web web

ENV COHORT_DB=/app/data/patients.duckdb \
    COHORT_LOG=/app/data/events.jsonl \
    PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "cohort.api:app", "--host", "0.0.0.0", "--port", "8080"]
