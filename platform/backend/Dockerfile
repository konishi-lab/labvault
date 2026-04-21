# syntax=docker/dockerfile:1.7
# FastAPI backend. Build context = repo root (needs labvault SDK in ../src).
#   docker build -f platform/backend/Dockerfile -t labvault-api .

FROM python:3.12-slim

WORKDIR /srv

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# labvault SDK + platform/backend を入れる
COPY pyproject.toml README.md ./
COPY src ./src
COPY platform/backend/requirements.txt ./platform_requirements.txt

RUN pip install ".[gcp,nextcloud,numpy]" -r platform_requirements.txt

COPY platform/backend/app ./app
COPY platform/backend/seed_admin.py ./

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
