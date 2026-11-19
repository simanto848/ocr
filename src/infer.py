"""Full OCR pipeline: detect (DBNet ~11M) + recognize (TrOCR <500M)."""
import env_bootstrap  # noqa: F401  (must be first: pins all caches to external drive)
import os, argparse
from pathlib import Path
import cv2
import torch
from PIL import Image

from config import RECOGNIZER_ID, CHECKPOINTS, INFER_CONFIG
from detect import detect_boxes, get_detector, count_detector_params
from layout import merge_boxes_into_lines, attach_texts, group_lines_into_blocks, blocks_to_text
from model import load_recognizer, count_params, check_total_budget

def get_device():
    if torch.backends.mps.is_available(): return "mps"
    if torch.cuda.is_available(): return "cuda"
    return "cpu"

class OCRPipeline:
    def __init__(self, recognizer_path: str = None, device: str = None):
        self.device = device or get_device()
        rec_id = recognizer_path or os.environ.get("OCR_MODEL", RECOGNIZER_ID)
        # prefer fine-tuned checkpoints if they exist (all <0.5B).
        # v010_small_clean first: no Ref:-hallucination artifact, best val loss.
        candidates = [
            CHECKPOINTS / "v010_small_clean" / "best",
            CHECKPOINTS / "trocr-small-ocr-800" / "best",
            CHECKPOINTS / "trocr-small-ocr" / "best",
            CHECKPOINTS / "trocr-base-ocr" / "best",
            CHECKPOINTS / "trocr-base-ocr" / "final",
        ]
        if recognizer_path is None:
            for c in candidates:
                if c.exists():
                    rec_id = str(c)
                    break
        print(f"Loading recognizer: {rec_id} on {self.device}")
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        self.processor = TrOCRProcessor.from_pretrained(rec_id)
        self.model = VisionEncoderDecoderModel.from_pretrained(rec_id).to(self.device).eval()
        rec_n = count_params(self.model)
        det = get_detector()
        det_n = count_detector_params(det)
        check_total_budget(rec_n, det_n)
        self.rec_n, self.det_n = rec_n, det_n

    @torch.no_grad()
    def recognize_crops(self, crops):
        texts = []
        bs = INFER_CONFIG["rec_batch_size"]
        for i in range(0, len(crops), bs):
            batch = crops[i:i+bs]
            pil = [Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)) for c in batch]
            pv = self.processor(images=pil, return_tensors="pt").pixel_values.to(self.device)
            ids = self.model.generate(pv, max_length=128, no_repeat_ngram_size=3, early_stopping=True)
            texts.extend(self.processor.batch_decode(ids, skip_special_tokens=True))
        return [t.strip() for t in texts]

    def __call__(self, image_path: str, line_mode: bool = False):
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(image_path)
        h, w = img.shape[:2]
        # Single-line images (h<150) or --line: skip detection, use whole image (much more accurate)
        if line_mode or h < 150:
            texts = self.recognize_crops([img])
            return {"results": [{"box": [0, 0, w, h], "text": texts[0]}],
                    "full_text": texts[0],
                    "params": {"recognizer": self.rec_n, "detector": self.det_n,
                               "total": self.rec_n + self.det_n}}
        word_boxes = detect_boxes(img)
        line_boxes = merge_boxes_into_lines(word_boxes)
        crops = []
        for (x1, y1, x2, y2) in line_boxes:
            pad = 4
            x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
            x2, y2 = min(img.shape[1], x2 + pad), min(img.shape[0], y2 + pad)
            crops.append(img[y1:y2, x1:x2])
        texts = self.recognize_crops(crops)
        lines = attach_texts(line_boxes, texts)
        blocks = group_lines_into_blocks([l for l in lines if l["text"].strip()] or lines)
        full = blocks_to_text(blocks)
        return {"results": lines, "blocks": blocks, "full_text": full,
                "params": {"recognizer": self.rec_n, "detector": self.det_n,
                           "total": self.rec_n + self.det_n}}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="image / scanned doc path")
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--line", action="store_true", help="single-line image: skip detection")
    args = ap.parse_args()
    pipe = OCRPipeline(args.model)
    r = pipe(args.image, line_mode=args.line)
    print(f"--- FULL TEXT ---\n{r['full_text']}\n-----------------")
    for it in r["results"]:
        print(f"{it['box']} -> {it['text']}")
    print(f"Params total: {r['params']['total']/1e6:.1f}M")
    if args.out:
        Path(args.out).write_text(r["full_text"])
        print(f"saved -> {args.out}")

if __name__ == "__main__":
    main()
