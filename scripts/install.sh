#!/bin/bash
set -e
# host prep for Ubuntu 22.04+ with NVIDIA GPU passthrough already attached
apt-get update && apt-get install -y docker.io curl iptables
# nvidia container toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia.gpg] https://#' > /etc/apt/sources.list.d/nvidia.list
apt-get update && apt-get install -y nvidia-container-toolkit && nvidia-ctk runtime configure --runtime=docker || true
systemctl restart docker
# weekly prune old artifacts
(crontab -l 2>/dev/null; echo "0 4 * * 0 find $(pwd)/artifacts -mtime +7 -delete && docker system prune -f") | crontab -
echo "install done. next: cp .env.example .env, edit tokens, docker compose up --build -d"
