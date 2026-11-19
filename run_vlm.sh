#!/bin/zsh
# Start the PaddleOCR-VL OCR service (layout-aware Markdown, 109 languages).
# First run downloads ~2 GB of weights to .cache/paddlex on the external drive.
cd "$(dirname "$0")" || exit 1
export PADDLE_PDX_CACHE_HOME="$PWD/.cache/paddlex"
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
# NOTE: do NOT set PADDLE_PDX_CPU_NUM_THREADS — it triggers a Paddle static-graph
# bug ("int(Tensor) is not supported in static graph mode") during VLM inference.
mkdir -p "$PADDLE_PDX_CACHE_HOME"
exec .venv-paddle/bin/python -u src/vlm_service.py --port "${1:-8090}"
