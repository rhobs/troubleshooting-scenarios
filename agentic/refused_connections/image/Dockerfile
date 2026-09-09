FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/gateway
COPY gateway_proxy.py .

RUN chgrp -R 0 /opt/gateway && chmod -R g=u /opt/gateway

USER 1001
EXPOSE 8080
ENTRYPOINT ["python3", "-m", "gateway_proxy"]
