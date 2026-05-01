FROM --platform=linux/amd64 ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /workspace/requirements.txt
RUN python3 -m pip install --break-system-packages -r /workspace/requirements.txt

WORKDIR /workspace
COPY . /workspace
