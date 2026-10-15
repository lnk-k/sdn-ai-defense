#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Linux ]]; then
  echo '该脚本需要在 Ubuntu Linux 中运行。Mac 请先启动 Lima 虚拟机。' >&2
  exit 1
fi
if [[ -f /etc/apt/sources.list.d/ubuntu.sources ]]; then
  sudo sed -i.bak 's|http://ports.ubuntu.com|https://ports.ubuntu.com|g; s|http://archive.ubuntu.com|https://archive.ubuntu.com|g; s|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
fi
sudo --preserve-env=http_proxy,https_proxy,HTTP_PROXY,HTTPS_PROXY apt-get -o Acquire::ForceIPv4=true -o Acquire::Languages=none update
sudo --preserve-env=http_proxy,https_proxy,HTTP_PROXY,HTTPS_PROXY env DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::ForceIPv4=true install -y --no-install-recommends mininet openvswitch-switch iperf3 python3-venv iputils-ping
sudo systemctl enable --now openvswitch-switch
python3 -m venv --system-site-packages .venv-linux
.venv-linux/bin/python -m pip install -r requirements-dev.txt
echo 'Linux 环境安装完成。'
