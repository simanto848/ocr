"""Central config. Everything paths point inside OCR_ROOT (external drive)."""
import env_bootstrap  # noqa: F401  (must be first: pins all caches to external drive)
import os
from pathlib import Path

ROOT = Path(os.environ.get("OCR_ROOT", str(Path(__file__).resolve().parents[1])))
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_SYNTHETIC = ROOT / "data" / "synthetic"
CHECKPOINTS = ROOT / "checkpoints"
OUTPUTS = ROOT / "outputs"
LOGS = ROOT / "logs"

# ---- Model choice: must stay < 0.5B params ----
# Recognizer: microsoft/trocr-base-printed = 334M params (ViT-Base 86M + RoBERTa-large-ish decoder)
# Detector: doctr db_mobilenet_v3_large = ~11M params
# Total ~345M < 500M  ✅
RECOGNIZER_ID = "microsoft/trocr-base-printed"
RECOGNIZER_SMALL_ID = "microsoft/trocr-small-printed"  # 62M fallback if OOM
DETECTOR_ID = "db_mobilenet_v3_large"  # doctr pretrained, ~11M

MAX_PARAMS = 500_000_000

TRAIN_CONFIG = dict(
    recognizer_id=RECOGNIZER_ID,
    output_dir=str(CHECKPOINTS / "trocr-base-ocr"),
    max_steps=2000,
    batch_size=8,
    grad_accum=2,        # effective 16
    lr=5e-5,
    warmup_ratio=0.05,
    eval_every=200,
    save_every=200,
    max_target_length=128,
    image_size=(384, 384),
    seed=42,
)

# Inference
INFER_CONFIG = dict(
    det_thresh=0.3,
    box_thresh=0.4,
    min_box_area=100,
    rec_batch_size=8,
)
