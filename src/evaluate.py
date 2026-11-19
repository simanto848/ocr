"""Evaluate OCR accuracy: CER / WER / Exact Match."""
import env_bootstrap  # noqa: F401  (must be first: pins all caches to external drive)
import argparse
from pathlib import Path
import jiwer

def load_tsv(tsv):
    pairs = []
    with open(tsv) as f:
        for line in f:
            if "\t" in line:
                img, txt = line.rstrip("\n").split("\t", 1)
                pairs.append((img, txt))
    return pairs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True, help="pred tsv: img\\ttext")
    ap.add_argument("--gt", required=True, help="gt tsv")
    args = ap.parse_args()
    pred = dict(l.split("\t", 1) for l in Path(args.pred).read_text().splitlines() if "\t" in l)
    gt = load_tsv(args.gt)
    refs, hyps = [], []
    em = 0
    for img, t in gt:
        key = img
        # allow basename match
        p = pred.get(key, pred.get(Path(key).name, ""))
        refs.append(t); hyps.append(p)
        if p.strip() == t.strip(): em += 1
    # jiwer needs non-empty
    cer = jiwer.cer(refs, hyps)
    wer = jiwer.wer(refs, hyps)
    print(f"samples: {len(refs)}")
    print(f"CER: {cer:.4f}  (accuracy {100*(1-cer):.2f}%)")
    print(f"WER: {wer:.4f}")
    print(f"Exact match: {em}/{len(refs)} = {em/len(refs)*100:.2f}%")

if __name__ == "__main__":
    main()
