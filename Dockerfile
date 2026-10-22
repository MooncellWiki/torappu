# syntax=docker/dockerfile:1

# These multi-platform digests include the eMudhra CA distrust update.
FROM python:3.13-bookworm@sha256:d0d07bbf0643a833ef149a44626a827dd42b748a7d6fa1d6bc9c4d878029bf0f AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /bin/uv

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

FROM python:3.13-slim-bookworm@sha256:a881a81282cca8c57f97014867fa651def1b3799030cc6b1cff45ed55ba8ef36

WORKDIR /app

ENV TZ=Asia/Shanghai \
  PATH=/opt/venv/bin:$PATH \
  HOME=/tmp

# A numeric UID lets Kubernetes verify runAsNonRoot.
# HOME also covers arbitrary runtime UIDs without a passwd entry.
RUN groupadd --gid 10001 torappu \
  && useradd --uid 10001 --gid 10001 --no-create-home --no-log-init \
    --home-dir /tmp --shell /usr/sbin/nologin torappu \
  && install -d -o 10001 -g 10001 -m 0755 /app/storage \
    /app/storage/asset /app/storage/assetbundle /app/storage/hot_update_list

COPY --from=builder /opt/ffmpeg/ /usr/bin/
COPY --from=builder /opt/venv /opt/venv

# Tag name or short sha, passed in by CI; picked up by sentry-sdk as the release.
ARG VERSION=dev
ENV SENTRY_RELEASE=torappu@${VERSION}

COPY . /app/

# Normalize both restrictive and permissive build-context modes.
# Keep the code root-owned and readable, without group/other write access.
RUN chmod -R u=rwX,go=rX /app \
  && python -m compileall -q /app/torappu

USER 10001:10001

ENTRYPOINT ["torappu", "run"]
