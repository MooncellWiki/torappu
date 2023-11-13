FROM python:3.10-bookworm as requirements-stage

WORKDIR /tmp

RUN curl -sSL https://install.python-poetry.org | python -

ENV PATH="${PATH}:/root/.local/bin"

COPY ./pyproject.toml ./poetry.lock* /tmp/

RUN poetry export -f requirements.txt --output requirements.txt --without-hashes

FROM python:3.10-bookworm as build-stage

WORKDIR /wheel

COPY --from=requirements-stage /tmp/requirements.txt /wheel/requirements.txt

RUN pip wheel --wheel-dir=/wheel --no-cache-dir --requirement /wheel/requirements.txt

FROM python:3.10-bullseye as metadata-stage

WORKDIR /tmp

RUN --mount=type=bind,source=./.git/,target=/tmp/.git/ \
  git describe --tags --exact-match > /tmp/VERSION 2>/dev/null \
  || git rev-parse --short HEAD > /tmp/VERSION \
  && echo "Building version: $(cat /tmp/VERSION)"

FROM python:3.10-slim-bookworm

WORKDIR /app

ENV TZ Asia/Shanghai
ENV DEBIAN_FRONTEND noninteractive

ENV PYTHONPATH=/app

RUN apt-get update && apt-get -y install ca-certificates

EXPOSE 8000

COPY --from=build-stage /wheel /wheel

RUN pip install --no-cache-dir --no-index --find-links=/wheel -r /wheel/requirements.txt && rm -rf /wheel

COPY --from=metadata-stage /tmp/VERSION /app/VERSION

RUN apt-get update && apt-get -y install ffmpeg

COPY OpenArknightsFBS /app/OpenArknightsFBS

COPY torappu /app/torappu

COPY bin /app/bin
RUN chmod -R +x /app/bin

CMD ["python", "-m", "torappu.server"]
