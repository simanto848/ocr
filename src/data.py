"""Dataset for TrOCR fine-tuning. Expects TSV: images/<file>\\t<text>."""
import env_bootstrap  # noqa: F401  (must be first: pins all caches to external drive)
import os
from pathlib import Path
from PIL import Image
import torch
from torch.utils.data import Dataset

class OCRTsvDataset(Dataset):
    def __init__(self, tsv_path, images_root, processor, max_target_length=128):
        self.root = Path(images_root)
        self.processor = processor
        self.max_target_length = max_target_length
        self.items = []
        with open(tsv_path) as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or "\t" not in line:
                    continue
                img_rel, txt = line.split("\t", 1)
                p = self.root / img_rel if not os.path.isabs(img_rel) else Path(img_rel)
                if p.exists():
                    self.items.append((str(p), txt))
        print(f"Loaded {len(self.items)} samples from {tsv_path}")

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        path, text = self.items[idx]
        img = Image.open(path).convert("RGB")
        pixel_values = self.processor(img, return_tensors="pt").pixel_values.squeeze(0)
        labels = self.processor.tokenizer(
            text, padding="max_length", max_length=self.max_target_length,
            truncation=True, return_tensors="pt"
        ).input_ids.squeeze(0)
        labels[labels == self.processor.tokenizer.pad_token_id] = -100
        return {"pixel_values": pixel_values, "labels": labels, "text": text}
