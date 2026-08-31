#!/bin/bash
# 微信实时字幕 macOS 版 · 一键安装
set -e
cd "$(dirname "$0")"

MODEL="${1:-sherpa-onnx-x-asr-960ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05}"

PY=$(command -v python3.11 || command -v python3.12 || command -v python3)
echo "[1/4] 创建虚拟环境（$PY）..."
[ -d .venv ] || "$PY" -m venv .venv
./.venv/bin/pip install -q -U pip

echo "[2/4] 安装依赖..."
./.venv/bin/pip install -q -r requirements.txt

echo "[3/4] 下载识别模型 $MODEL ..."
mkdir -p models
if [ ! -d "models/$MODEL" ]; then
  curl -L --fail --progress-bar \
    -o "models/$MODEL.tar.bz2" \
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$MODEL.tar.bz2"
  tar -xjf "models/$MODEL.tar.bz2" -C models
  rm -f "models/$MODEL.tar.bz2"
  rm -rf "models/$MODEL/test_wavs"
fi

echo "[4/4] 构建 .app ..."
./make_app.sh

echo
echo "完成。占用：$(du -sh . | cut -f1)"
echo "双击「微信实时字幕.app」即可使用（必须走 .app，命令行拿不到系统授权）"
