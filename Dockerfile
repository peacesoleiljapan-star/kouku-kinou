FROM python:3.12-slim

WORKDIR /app

COPY index.html ./index.html
COPY server.py ./server.py
COPY README.html ./README.html
COPY README.md ./README.md
COPY DEPLOY_SYNOLOGY_JA.md ./DEPLOY_SYNOLOGY_JA.md
COPY OPERATIONS_MANUAL_JA.md ./OPERATIONS_MANUAL_JA.md
COPY TAILSCALE_CLIENT_GUIDE_JA.md ./TAILSCALE_CLIENT_GUIDE_JA.md
COPY TAILSCALE_TABLET_GUIDE_JA.md ./TAILSCALE_TABLET_GUIDE_JA.md
COPY TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.md ./TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.md
COPY TAILSCALE_TABLET_QR_SHEET_JA.md ./TAILSCALE_TABLET_QR_SHEET_JA.md
COPY TailscaleClientLauncher.cmd ./TailscaleClientLauncher.cmd
COPY TailscaleClientLauncher.ps1 ./TailscaleClientLauncher.ps1
COPY TailscaleClientLauncher.settings.json ./TailscaleClientLauncher.settings.json
COPY .env.example ./.env.example
COPY assets ./assets

EXPOSE 8010
VOLUME ["/data"]

ENV KOUKU_KINOU_DB=/data/records.db

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8010", "--db", "/data/records.db"]