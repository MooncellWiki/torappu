# syntax=docker/dockerfile:1

FROM python:3.12-bookworm AS requirements-stage

WORKDIR /tmp

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="${PATH}:/root/.local/bin"

COPY ./pyproject.toml ./uv.lock* /tmp/

RUN uv export --format requirements.txt -o requirements.txt --no-editable --no-hashes --no-dev --no-emit-project

FROM python:3.12-bookworm AS build-stage

WORKDIR /wheel

COPY --from=requirements-stage /tmp/requirements.txt /wheel/requirements.txt

RUN pip wheel --wheel-dir=/wheel --no-cache-dir --requirement /wheel/requirements.txt

FROM python:3.12-bookworm AS metadata-stage

WORKDIR /tmp

RUN --mount=type=bind,source=./.git/,target=/tmp/.git/ \
  git describe --tags --exact-match > /tmp/VERSION 2>/dev/null \
  || git rev-parse --short HEAD > /tmp/VERSION \
  && echo "Building version: $(cat /tmp/VERSION)"

FROM python:3.12-slim-bookworm

WORKDIR /app

ENV TZ=Asia/Shanghai DEBIAN_FRONTEND=noninteractive PYTHONPATH=/app

RUN ARCH=$(uname -m | sed 's/^aarch64$/arm64/') \
  && FOLDER="ffmpeg-8.0-audio-$ARCH-linux-gnu" \
  && apt-get update \
  && apt-get install -y --no-install-recommends curl \
  && curl -sSL "https://github.com/acoustid/ffmpeg-build/releases/download/v8.0-1/$FOLDER.tar.gz" -o /tmp/ffmpeg.tar.gz \
  && tar -xzf /tmp/ffmpeg.tar.gz -C /tmp/ \
  && cd /tmp/$FOLDER/bin/ \
  && mv * /usr/bin/ \
  && chmod +x /usr/bin/ffmpeg /usr/bin/ffprobe \
  && apt-get purge -y --auto-remove curl \
  && rm -rf /tmp/ffmpeg.tar.gz /tmp/$FOLDER

COPY --from=build-stage /wheel /wheel

RUN pip install --no-cache-dir --no-index --find-links=/wheel -r /wheel/requirements.txt && rm -rf /wheel

COPY --from=metadata-stage /tmp/VERSION /app/VERSION

COPY . /app/

RUN chmod -R +x /app/bin

ENTRYPOINT ["python", "-m", "torappu"]
