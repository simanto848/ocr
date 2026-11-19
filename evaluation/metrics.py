"""Shared CER/WER with configurable normalization (raw + normalized)."""
from __future__ import annotations
import re, unicodedata
import jiwer

def normalize(t: str, lowercase=False, collapse_ws=True) -> str:
    t = unicodedata.normalize("NFC", t)
    if collapse_ws:
        t = re.sub(r"\s+", " ", t).strip()
    # Bangla punctuation variants
    t = t.replace("।।", "।")
    if lowercase:
        t = t.lower()
    return t

def cer_wer(refs, hyps, lowercase=False):
    r = [normalize(x, lowercase) for x in refs]
    h = [normalize(x, lowercase) for x in hyps]
    r = [x or " " for x in r]; h = [x or " " for x in h]
    return {"cer": float(jiwer.cer(r, h)), "wer": float(jiwer.wer(r, h)),
            "cer_raw": float(jiwer.cer(refs, hyps))}

def group_scores(items):
    """items: list of dicts with keys group, ref, hyp → per-group CER/WER."""
    from collections import defaultdict
    g = defaultdict(lambda: {"refs": [], "hyps": []})
    for it in items:
        g[it["group"]]["refs"].append(it["ref"]); g[it["group"]]["hyps"].append(it["hyp"])
    out = {}
    for k, v in g.items():
        try:
            out[k] = {"n": len(v["refs"]), **cer_wer(v["refs"], v["hyps"])}
        except Exception as e:
            out[k] = {"n": len(v["refs"]), "error": str(e)[:100]}
    return out
