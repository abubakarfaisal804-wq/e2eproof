FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/e2eproof
COPY . .
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-build-isolation . \
    && e2eproof install-browser chromium --with-deps \
    && rm -rf /root/.cache/pip

WORKDIR /work
ENTRYPOINT ["e2eproof"]
CMD ["--help"]
