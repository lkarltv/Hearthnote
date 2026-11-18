FROM python:3.12-slim

WORKDIR /app
COPY app ./app

ENV HOST=0.0.0.0 \
    PORT=8000 \
    NOTES_ROOT=/notes \
    HEARTHNOTE_DATA_DIR=/data

EXPOSE 8000
CMD ["python", "-m", "app.server"]

