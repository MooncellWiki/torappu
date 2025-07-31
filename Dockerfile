# syntax=docker/dockerfile:1

FROM python:3.12-bookworm AS requirements-stage

WORKDIR /tmp

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="${PATH}:/root/.local/bin"

COPY ./pyproject.toml ./uv.lock* /tmp/

RUN uv export --format requirements.txt -o requirements.txt --no-hashes

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

RUN apt-get update && apt-get -y install ffmpeg

COPY --from=build-stage /wheel /wheel

RUN pip install --no-cache-dir --no-index --find-links=/wheel -r /wheel/requirements.txt && rm -rf /wheel

COPY --from=metadata-stage /tmp/VERSION /app/VERSION

COPY . /app/

RUN chmod -R +x /app/bin

ENTRYPOINT ["python", "-m", "torappu"]
