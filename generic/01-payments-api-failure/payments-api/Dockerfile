FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py log_config.yaml .

USER 1001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--log-config", "log_config.yaml"]
