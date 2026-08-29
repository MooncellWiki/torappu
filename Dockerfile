# syntax=docker/dockerfile:1

FROM python:3.13-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /bin/uv

ENV UV_LINK_MODE=copy \
  UV_COMPILE_BYTECODE=1 \
  UV_PYTHON_DOWNLOADS=never \
  UV_PROJECT_ENVIRONMENT=/opt/venv

# ffmpeg (audio-only build). Fetched here so the runtime image never needs apt/curl.
RUN ARCH=$(uname -m | sed 's/^aarch64$/arm64/') \
  && mkdir -p /opt/ffmpeg \
  && curl -fsSL "https://github.com/MooncellWiki/ffmpeg-build/releases/download/v8.0-3/ffmpeg-8.0-audio-$ARCH-linux-gnu.tar.gz" \
  | tar -xz -C /opt/ffmpeg --strip-components=2 --wildcards '*/bin/*' \
  && chmod +x /opt/ffmpeg/*

WORKDIR /app

# Dependencies only; the project itself runs from /app via PYTHONPATH.
# Bind-mounting just uv.lock/pyproject.toml keeps this layer cached across
# source-only changes. uv builds sdist-only packages (UnityPy / ark-fbs on
# arm64) in parallel.
RUN --mount=type=cache,target=/root/.cache/uv \
  --mount=type=bind,source=uv.lock,target=uv.lock \
  --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
  uv sync --locked --no-dev --no-install-project

FROM python:3.13-slim-bookworm

WORKDIR /app

ENV TZ=Asia/Shanghai \
  PYTHONPATH=/app \
  PATH=/opt/venv/bin:$PATH

COPY --from=builder /opt/ffmpeg/ /usr/bin/
COPY --from=builder /opt/venv /opt/venv

# Tag name or short sha, passed in by CI; picked up by sentry-sdk as the release.
ARG VERSION=dev
ENV SENTRY_RELEASE=torappu@${VERSION}

COPY . /app/

ENTRYPOINT ["python", "-m", "torappu"]
