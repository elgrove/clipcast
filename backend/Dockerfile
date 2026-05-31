# Stage 1: Build frontend
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Download s6-overlay tarballs
FROM alpine AS s6-stage
ARG TARGETARCH
RUN apk add --no-cache wget
RUN wget -q "https://github.com/just-containers/s6-overlay/releases/download/v3.2.0.2/s6-overlay-noarch.tar.xz" -O /s6-noarch.tar.xz
RUN wget -q "https://github.com/just-containers/s6-overlay/releases/download/v3.2.0.2/s6-overlay-x86_64.tar.xz" -O /s6-x86_64.tar.xz
RUN wget -q "https://github.com/just-containers/s6-overlay/releases/download/v3.2.0.2/s6-overlay-aarch64.tar.xz" -O /s6-aarch64.tar.xz

# Stage 3: Python backend with s6-overlay
FROM python:3.11-slim AS backend
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    sqlite3 \
    redis-server \
    xz-utils \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-cache --no-dev

COPY backend/app/ ./app/
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic/ ./alembic/

# Copy built frontend into static directory
COPY --from=frontend-build /app/frontend/build ./static/frontend

# Install s6-overlay
COPY --from=s6-stage /s6-noarch.tar.xz /s6-aarch64.tar.xz /s6-x86_64.tar.xz /tmp/
RUN tar -C / -Jxpf /tmp/s6-noarch.tar.xz \
    && if [ "$TARGETARCH" = "arm64" ]; then \
         tar -C / -Jxpf /tmp/s6-aarch64.tar.xz; \
       else \
         tar -C / -Jxpf /tmp/s6-x86_64.tar.xz; \
       fi \
    && rm /tmp/s6-*.tar.xz

# Copy s6 service definitions
COPY backend/s6/ /etc/s6-overlay/

ENV S6_BEHAVIOUR_IF_STAGE2_FAILS=2
ENV PYTHONUNBUFFERED=1

EXPOSE 8906

ENTRYPOINT ["/init"]
