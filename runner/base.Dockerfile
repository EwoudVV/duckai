FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu124 || pip3 install --no-cache-dir torch
ENV HF_HOME=/w/.cache HF_HUB_OFFLINE=0
WORKDIR /w
