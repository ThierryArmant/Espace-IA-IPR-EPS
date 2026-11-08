FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HUB_DATABASE=/var/lib/ipr/hub.sqlite3
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 hub \
    && useradd --uid 10001 --gid 10001 --no-create-home hub \
    && install -d -m 0700 -o hub -g hub /var/lib/ipr /app/instance
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py login_code.py nuage_hub.py nuage_pilote.py ipr_modules.py schema.sql ipr_schema.sql ./
COPY templates/ templates/
COPY static/ static/
USER hub
CMD ["waitress-serve", "--listen=0.0.0.0:8080", "--max-request-body-size=34603008", "--call", "app:create_app"]
