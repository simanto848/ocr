"""Text detection with doctr DBNet (stays on external drive via HF_HOME)."""
import env_bootstrap  # noqa: F401  (must be first: pins all caches to external drive)
import cv2
import numpy as np

_detector = None

def get_detector(det_arch: str = "db_mobilenet_v3_large", pretrained: bool = True):
    global _detector
    if _detector is not None:
        return _detector
    import os
    if not os.environ.get("DOCTR_CACHE_DIR", "").startswith(os.environ.get("OCR_ROOT", "/Volumes/SSD-SIMANTO/works/ocr")):
        raise RuntimeError("DOCTR_CACHE_DIR must point inside OCR_ROOT (source ./env.sh) — refusing to download to internal disk")
    from doctr.models import detection_predictor
    _detector = detection_predictor(
        det_arch, pretrained=pretrained,
        assume_straight_pages=True,
    )
    return _detector

def count_detector_params(det) -> int:
    try:
        n = sum(p.numel() for p in det.model.parameters())
        print(f"[detector] ~{n/1e6:.1f}M params")
        return int(n)
    except Exception:
        # doctr mobilenet db ~11M documented
        print("[detector] ~11.0M params (documented)")
        return 11_000_000

def detect_boxes(image_bgr: np.ndarray, det_thresh: float = 0.3):
    """Return list of [x1,y1,x2,y2] in pixel coords. doctr>=0.8 returns list of dicts."""
    det = get_detector()
    h, w = image_bgr.shape[:2]
    # doctr expects RGB numpy
    img_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    out = det([img_rgb])
    boxes = []
    # new API: list[{ 'words': array Nx5, 'lines': ... }]
    # old API: Document with .pages
    try:
        if isinstance(out, list):
            for page in out:
                words = None
                if isinstance(page, dict):
                    words = page.get("words", None)
                elif hasattr(page, "get"):
                    words = page.get("words", None)
                if words is None:
                    continue
                for (x1n, y1n, x2n, y2n, score) in words:
                    if float(score) < det_thresh:
                        continue
                    x1, y1 = int(float(x1n) * w), int(float(y1n) * h)
                    x2, y2 = int(float(x2n) * w), int(float(y2n) * h)
                    if (x2 - x1) * (y2 - y1) < 100:
                        continue
                    boxes.append([max(0, x1), max(0, y1), min(w, x2), min(h, y2)])
        elif hasattr(out, "pages"):
            for page in out.pages:
                for block in page.blocks:
                    for line in block.lines:
                        for word in line.words:
                            (xmin, ymin), (xmax, ymax) = word.geometry
                            x1, y1 = int(xmin * w), int(ymin * h)
                            x2, y2 = int(xmax * w), int(ymax * h)
                            if (x2 - x1) * (y2 - y1) < 100:
                                continue
                            boxes.append([max(0, x1), max(0, y1), min(w, x2), min(h, y2)])
    except Exception as e:
        print(f"[detect] warning: {e}")
    # fallback: whole image if nothing found (single-line crops)
    if not boxes:
        boxes = [[0, 0, w, h]]
    boxes = sorted(boxes, key=lambda b: (b[1] // 20, b[0]))
    return boxes
