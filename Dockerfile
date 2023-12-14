# syntax=docker/dockerfile:1

FROM python:3.11-bookworm as requirements-stage

WORKDIR /tmp

RUN curl -sSL https://install.python-poetry.org | python -

ENV PATH="${PATH}:/root/.local/bin"

COPY ./pyproject.toml ./poetry.lock* /tmp/

RUN poetry export -f requirements.txt --output requirements.txt --without-hashes --with deploy

FROM python:3.11-bookworm as build-stage

WORKDIR /wheel

COPY --from=requirements-stage /tmp/requirements.txt /wheel/requirements.txt

# RUN python3 -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple

RUN pip wheel --wheel-dir=/wheel --no-cache-dir --requirement /wheel/requirements.txt

FROM python:3.11-bookworm as metadata-stage

WORKDIR /tmp

RUN --mount=type=bind,source=./.git/,target=/tmp/.git/ \
  git describe --tags --exact-match > /tmp/VERSION 2>/dev/null \
  || git rev-parse --short HEAD > /tmp/VERSION \
  && echo "Building version: $(cat /tmp/VERSION)"

FROM python:3.11-slim-bookworm

WORKDIR /app

ENV TZ Asia/Shanghai
ENV DEBIAN_FRONTEND noninteractive

COPY ./docker/start.sh /start.sh
RUN chmod +x /start.sh

COPY ./docker/gunicorn_conf.py /gunicorn_conf.py

ENV PYTHONPATH=/app

EXPOSE 8000

ENV APP_MODULE torappu.server.__main__:app

# RUN mv /etc/apt/sources.list /etc/apt/sources.list.bak &&\
#   echo "deb http://mirrors.aliyun.com/debian/ buster main" >> /etc/apt/sources.list\
#   && echo "deb http://mirrors.aliyun.com/debian/ buster-updates main" >> /etc/apt/sources.list\
#   && echo "deb http://mirrors.aliyun.com/debian-security/ buster/updates main" >> /etc/apt/sources.list

COPY --from=build-stage /wheel /wheel

RUN pip install --no-cache-dir --no-index --find-links=/wheel -r /wheel/requirements.txt && rm -rf /wheel

COPY --from=metadata-stage /tmp/VERSION /app/VERSION

RUN apt-get update && apt-get -y install ffmpeg

COPY . /app/
RUN chmod -R +x /app/bin

CMD ["/start.sh"]
