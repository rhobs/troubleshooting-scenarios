FROM python:3.12-slim

ARG APP_VERSION
ENV APP_VERSION=${APP_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/report-generator
COPY worker.py ./worker.py
COPY releases/${APP_VERSION}/report_cache.py ./report_cache.py
RUN chmod -R a=rX /opt/report-generator

USER 1001
ENTRYPOINT ["python3", "-u", "-m", "worker"]
