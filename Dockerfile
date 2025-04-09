# syntax=docker/dockerfile:1

FROM python:3.11-bookworm AS requirements-stage

WORKDIR /tmp

RUN curl -sSL https://install.python-poetry.org | python -

ENV PATH="${PATH}:/root/.local/bin"

COPY ./pyproject.toml ./poetry.lock* /tmp/

RUN poetry self add poetry-plugin-export && \
  poetry export -f requirements.txt --output requirements.txt --without-hashes --with deploy

FROM python:3.11-bookworm AS build-stage

WORKDIR /wheel

COPY --from=requirements-stage /tmp/requirements.txt /wheel/requirements.txt

RUN pip wheel --wheel-dir=/wheel --no-cache-dir --requirement /wheel/requirements.txt

FROM python:3.11-bookworm AS metadata-stage

WORKDIR /tmp

RUN --mount=type=bind,source=./.git/,target=/tmp/.git/ \
  git describe --tags --exact-match > /tmp/VERSION 2>/dev/null \
  || git rev-parse --short HEAD > /tmp/VERSION \
  && echo "Building version: $(cat /tmp/VERSION)"

FROM python:3.11-slim-bookworm

WORKDIR /app

ENV TZ=Asia/Shanghai
ENV DEBIAN_FRONTEND=noninteractive

ENV PYTHONPATH=/app

EXPOSE 8000

RUN apt-get update && apt-get -y install ffmpeg

COPY --from=build-stage /wheel /wheel

# https://github.com/MooncellWiki/torappu/actions/runs/14351050234/job/40229870098
RUN pip install wheel
RUN pip install --no-cache-dir --no-index --find-links=/wheel -r /wheel/requirements.txt && rm -rf /wheel

COPY --from=metadata-stage /tmp/VERSION /app/VERSION

COPY ./patches/UnityPy/files/BundleFile.py /usr/local/lib/python3.11/site-packages/UnityPy/files/

COPY . /app/
RUN chmod -R +x /app/bin

CMD ["python", "-m", "torappu.server"]
