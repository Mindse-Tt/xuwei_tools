#!/bin/bash
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "还没安装，请先运行:  ./install.sh"; exit 1
fi
exec ./.venv/bin/python app_mac.py "$@"
