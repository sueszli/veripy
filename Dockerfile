FROM ubuntu:22.04

RUN apt-get update && apt-get install -y wget unzip && \
    wget -q https://github.com/dafny-lang/dafny/releases/download/v4.9.2/dafny-4.9.2-x64-ubuntu-20.04.zip -O /tmp/dafny.zip && \
    unzip /tmp/dafny.zip -d /opt && \
    rm /tmp/dafny.zip && \
    apt-get clean
ENV PATH="/opt/dafny:$PATH"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY . /app
WORKDIR /app
RUN uv sync
