#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
mkdir -p models
if [ ! -d models/vosk-model-small-ru-0.22 ]; then
 curl -fL https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip -o models/vosk.zip
 unzip -q models/vosk.zip -d models
 rm models/vosk.zip
fi
if [ ! -f models/qwen3-4b.gguf ]; then
 curl -fL -C - https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf -o models/qwen3-4b.gguf.part
 mv models/qwen3-4b.gguf.part models/qwen3-4b.gguf
fi
for suffix in onnx onnx.json; do
 if [ ! -f "models/voice.$suffix" ]; then
  curl -fL "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.$suffix" -o "models/voice.$suffix.part"
  mv "models/voice.$suffix.part" "models/voice.$suffix"
 fi
done
