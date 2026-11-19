# Source this file: source ./env.sh
# Forces EVERYTHING onto the external drive: /Volumes/SSD-SIMANTO/works/ocr
export OCR_ROOT="/Volumes/SSD-SIMANTO/works/ocr"
export VIRTUAL_ENV="$OCR_ROOT/.venv"
export PATH="$OCR_ROOT/.venv/bin:$PATH"

# Python / pip -> external only
export PIP_CACHE_DIR="$OCR_ROOT/.cache/pip"
export PIP_TARGET="$OCR_ROOT/.venv/lib/python3.11/site-packages"
export PYTHONUSERBASE="$OCR_ROOT/.local"
export PYTHONPATH="$OCR_ROOT/src:$PYTHONPATH"

# HuggingFace / Torch / datasets / doctr -> external only
export HF_HOME="$OCR_ROOT/.cache/huggingface"
export HUGGINGFACE_HUB_CACHE="$OCR_ROOT/.cache/huggingface/hub"
export TRANSFORMERS_CACHE="$OCR_ROOT/.cache/huggingface/hub"
export HF_DATASETS_CACHE="$OCR_ROOT/.cache/datasets"
export TORCH_HOME="$OCR_ROOT/.cache/torch"
export TORCH_HUB="$OCR_ROOT/.cache/torch/hub"
export DOCTR_CACHE_DIR="$OCR_ROOT/.cache/doctr"
export FONTS_DIR="$OCR_ROOT/fonts"
export PLAYWRIGHT_BROWSERS_PATH="$OCR_ROOT/.cache/ms-playwright"
export XDG_CACHE_HOME="$OCR_ROOT/.cache"
export TMPDIR="$OCR_ROOT/.cache/tmp"
export MPLCONFIGDIR="$OCR_ROOT/.cache/matplotlib"

mkdir -p "$PIP_CACHE_DIR" "$HF_HOME" "$TORCH_HOME" "$TMPDIR" "$MPLCONFIGDIR" "$OCR_ROOT/.cache/datasets" "$DOCTR_CACHE_DIR" "$PLAYWRIGHT_BROWSERS_PATH" "$FONTS_DIR"

echo "OCR env active. Root=$OCR_ROOT"
echo "python: $(which python)"
echo "HF_HOME=$HF_HOME"
