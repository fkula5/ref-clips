# Obraz aplikacji ref-clips: jeden dla serwera WWW (app) i workera — różnią się tylko komendą.
# Budowanie: docker compose build   (albo: docker build -t ref-clips .)
FROM python:3.12-slim-bookworm

# ffmpeg z pakietów Debiana (bez zbędnych pakietów polecanych), listy apt czyścimy.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Użytkownik bez uprawnień roota; stałe UID/GID (można zmienić, gdy dane są na zwykłym katalogu hosta).
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

# Zależności przed kodem — zmiana kodu nie unieważnia tej warstwy. Baza stref czasowych dla `zoneinfo`
# (Europe/Warsaw) pochodzi z pakietu tzdata w requirements.txt, więc nie zależy od systemu obrazu.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Numer wersji pokazywany w stopce strony (zalogowani). Wdrożenie z GitHub Actions podaje go w
# --build-arg REFCLIPS_VERSION=vX.Y.Z; przy ręcznym budowaniu zostaje „dev”. Celowo po instalacji
# zależności i kopiowaniu kodu, żeby zmiana numeru nie unieważniała wcześniejszych warstw.
ARG REFCLIPS_VERSION=dev
ENV REFCLIPS_VERSION=$REFCLIPS_VERSION

# Katalog danych tworzymy i oddajemy użytkownikowi przed VOLUME: nowy, pusty wolumin
# dziedziczy ten właściciel, więc pierwszy start nie kończy się błędem uprawnień.
RUN mkdir /data && chown app:app /data
VOLUME /data

USER app
EXPOSE 8000

# /login jest publiczny i nie zdradza danych; sprawdza, że serwer odpowiada i działa szablon.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=4).status == 200 else 1)"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
