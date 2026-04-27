FROM python:3.12-slim

WORKDIR /app

COPY index.html ./index.html
COPY server.py ./server.py

EXPOSE 8010
VOLUME ["/data"]

ENV KOUKU_KINOU_DB=/data/records.db

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8010", "--db", "/data/records.db"]