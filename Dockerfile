FROM python:3.12-slim
ARG MARIMO_VERSION=0.24.2
RUN pip install --no-cache-dir marimo==${MARIMO_VERSION}
COPY src/herd/adapters/runner.py /opt/herd/runner.py
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
USER 65534:65534
WORKDIR /tmp
