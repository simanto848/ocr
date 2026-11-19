"""Dataset statistics + balancing report (dataset_statistics.json/html)."""
from __future__ import annotations
import json
from pathlib import Path
from collections import Counter

def compute_stats(manifests: list[dict]):
    c_lang, c_type, c_font, c_diff = Counter(), Counter(), Counter(), Counter()
    for m in manifests:
        c_lang[m.get("language", "?")] += 1
        c_type[m.get("document_type", "?")] += 1
        for f in m.get("fonts", []):
            c_font[f] += 1
        d = m.get("difficulty", 0)
        c_diff["easy" if d < 0.33 else "medium" if d < 0.66 else "hard"] += 1
    return {"n": len(manifests), "language": dict(c_lang), "document_type": dict(c_type),
            "fonts": dict(c_font), "difficulty": dict(c_diff)}

def difficulty_score(meta: dict, aug: dict) -> float:
    s = 0.0
    s += 0.2 if aug.get("rotation", 0) and abs(aug["rotation"]) > 2 else 0.05
    s += 0.15 if aug.get("perspective") else 0
    s += 0.1 if aug.get("blur") else 0
    s += 0.1 if aug.get("noise") else 0
    s += 0.1 if (meta.get("fonts") and len(meta["fonts"]) > 1) else 0
    s += 0.15 if meta.get("has_table") else 0
    return round(min(1.0, s), 2)
