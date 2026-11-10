# One image for the web server (app) and the worker; they differ only in the command.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Fixed UID/GID (can be changed when the data is on a plain host directory).
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "$APP_GID" app \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --no-create-home --shell /usr/sbin/nologin app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REFCLIPS_DATA_DIR=/data

WORKDIR /srv/app

# Dependencies before code, so a code change does not invalidate this layer. The `zoneinfo` timezone
# database (Europe/Warsaw) comes from the tzdata package in requirements.txt, not from the image's
# system.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Version shown in the page footer (logged-in users). GitHub Actions passes it as --build-arg
# REFCLIPS_VERSION=vX.Y.Z; manual builds stay "dev". Placed after installing dependencies and copying
# the code, so a version change does not invalidate earlier layers.
ARG REFCLIPS_VERSION=dev
ENV REFCLIPS_VERSION=$REFCLIPS_VERSION

# The data directory is created and handed to the user before VOLUME: a new empty volume inherits this
# owner, so the first start does not fail on permissions.
RUN mkdir /data && chown app:app /data
VOLUME /data

USER app
EXPOSE 8000

# /login is public and leaks nothing; it checks that the server answers and templates render.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=4).status == 200 else 1)"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
