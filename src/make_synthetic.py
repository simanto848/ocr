"""Synthetic printed-document data generator (for training)."""
import env_bootstrap  # noqa: F401  (must be first: pins all caches to external drive)
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import os

TEXTS = [
    "INVOICE No. 18473 Date: 12/04/2024 Total: $1,249.00",
    "The quick brown fox jumps over the lazy dog 1234567890",
    "Payment due within 30 days. Late fee 5% per month.",
    "Name: Simanto Sharma Address: Kathmandu, Nepal Phone: +977-98XXXXXXX",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789 .,!?-()",
    "Contract Agreement: Party A shall deliver goods by 30 Sept 2026.",
    "Blood Report: Hemoglobin 14.2 g/dL WBC 6.8k/uL Platelets 220k",
    "Machine learning OCR needs clean printed text and noise augmentation.",
]

def render_line(text, w=600, h=80, font_size=32):
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    try:
        # Use default bitmap font (always available)
        d.text((10, 10), text, fill="black")
    except Exception:
        d.text((10, 10), text, fill="black")
    return img

def make_synthetic(out_dir: str, n: int = 500, seed: int = 42):
    random.seed(seed)
    out = Path(out_dir)
    (out / "images").mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(n):
        t = random.choice(TEXTS)
        # NOTE: no artificial suffixes (a past "Ref:NNNNN" suffix taught the model
        # to hallucinate "Ref:..." on real documents — see TRAINING_REPORT.md).
        img = render_line(t, w=600, h=80)
        name = f"synth_{i:05d}.png"
        img.save(out / "images" / name)
        lines.append(f"images/{name}\t{t}")
    with open(out / "labels.tsv", "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote {n} synthetic samples to {out}")
    return str(out / "labels.tsv")

if __name__ == "__main__":
    root = os.environ.get("OCR_ROOT", "/Volumes/SSD-SIMANTO/works/ocr")
    make_synthetic(f"{root}/data/synthetic", n=1000)
