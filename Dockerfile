# syntax=docker/dockerfile:1

FROM python:3.13-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /bin/uv

ENV UV_LINK_MODE=copy \
  UV_COMPILE_BYTECODE=1 \
  UV_PYTHON_DOWNLOADS=never \
  UV_PROJECT_ENVIRONMENT=/opt/venv

# Static ffmpeg from MooncellWiki/ffmpeg-build: audio codecs plus the IVF/VP9,
# ADX and MP4/AAC components the Video task needs (v8.0-4+). Fetched here so
# the runtime image never needs apt/curl.
RUN ARCH=$(uname -m | sed 's/^aarch64$/arm64/') \
  && mkdir -p /opt/ffmpeg \
  && curl -fsSL "https://github.com/MooncellWiki/ffmpeg-build/releases/download/v8.0-4/ffmpeg-8.0-audio-$ARCH-linux-gnu.tar.gz" \
  | tar -xz -C /opt/ffmpeg --strip-components=2 --wildcards '*/bin/*' \
  && chmod +x /opt/ffmpeg/*

WORKDIR /app

# Dependencies first. Bind-mounting just uv.lock/pyproject.toml keeps this
# layer cached across source-only changes. uv builds sdist-only packages
# (UnityPy / ark-fbs on arm64) in parallel.
RUN --mount=type=cache,target=/root/.cache/uv \
  --mount=type=bind,source=uv.lock,target=uv.lock \
  --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
  uv sync --locked --no-dev --no-install-project

# Then the project itself as an editable install: that only drops a
# torappu.pth pointing at /app plus the dist-info into the venv, which is what
# provides the `torappu` console script and a real importlib.metadata version.
# The runtime stage's `COPY . /app/` is therefore the code that gets imported.
COPY pyproject.toml uv.lock README.md ./
COPY torappu ./torappu
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --locked --no-dev

FROM python:3.13-slim-bookworm

WORKDIR /app

ENV TZ=Asia/Shanghai \
  PATH=/opt/venv/bin:$PATH \
  PYTHONDONTWRITEBYTECODE=1 \
  HOME=/tmp

# A numeric UID lets Kubernetes verify runAsNonRoot. Root-group write access
# lets OpenShift's arbitrary UIDs use storage; setgid preserves that group.
RUN useradd --uid 10001 --gid 0 --no-create-home --no-log-init \
    --home-dir /tmp --shell /usr/sbin/nologin torappu \
  && install -d -o 10001 -g 0 -m 2775 /app/storage

COPY --from=builder /opt/ffmpeg/ /usr/bin/
COPY --from=builder /opt/venv /opt/venv

# Tag name or short sha, passed in by CI; picked up by sentry-sdk as the release.
ARG VERSION=dev
ENV SENTRY_RELEASE=torappu@${VERSION}

COPY . /app/

# Local build contexts may have restrictive modes (e.g. umask 077).
# Keep the code root-owned but readable, with bytecode ready before startup.
RUN chmod -R a+rX /app \
  && python -m compileall -q /app/torappu

USER 10001:0

ENTRYPOINT ["torappu", "run"]
