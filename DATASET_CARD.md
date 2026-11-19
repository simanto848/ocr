# DATASET_CARD.md

## Purpose
Train/evaluate sub-0.5B document OCR for Bangla, English, and mixed documents.

## Sources / licenses
- Text: deterministic in-house generators (`dataset/content/generators.py`) — no PII, no copyrighted text.
- Fonts (OFL, bundled in `fonts/`): Noto Sans Bengali, Noto Serif Bengali (Noto Project),
  Hind Siliguri R/M/B (Indian Type Foundry), Inter (Rasmus Andersson). System fonts used
  only as fallback and logged per-sample in `metadata/*.json → fallbacks`.
- Assets (logos/signatures/stamps): procedural, `source: synthetic`.

## Versions
| version | samples | seed | dpi | purpose |
|---|---|---|---|---|
| `data/v001` | 1,000 pp / 7,612 lines | 42 | 200 | Stage-1 validation, baseline, first fine-tune |
| `data/v010` | 10,000 pp (bn 3964 / en 3993 / bn-en 2043) | 43 | 200 | Stage-2 baseline; validation PASS 0% bad, 0 dups |
| `data/v011-hard` | 2,000 pp / 12,000 lines (invoice/gov_form/bn-heavy) | 43 | 200 | Mined from eval failures; second-cycle training |
| `real_world_test` | 12 proxy | 999 | 150+heavy | HELD-OUT. Synthetic stand-ins; replace with genuine scans |

Splits: deterministic 80/10/10 by sorted id (`splits.json`). Leakage control: distinct seeds
per version; content generators are seed-parameterized (no shared persons/numbers across versions
unless same seed).

## Distributions (v001)
- Language: bn 379 / en 400 / bn-en 221. Types: all 10 templates (62–153 each).
- Fonts: inter 588, noto_sans_bengali 587, noto_serif_bengali 484, hind_siliguri 492 docs.
- Tiers: clean 40% / light 30% / moderate 20% / heavy 10% (by design).

## Ground truth
From structured `Document` (never OCR): page text, line + word bboxes (degradation-transformed),
tables/KV in `document` field, per-sample augmentation record. Format:
`dataset/{images,annotations,metadata}/`, `manifest.json`, `splits.json`,
`{train,val,test}.tsv` (src-compatible), `lines/` line-crop export for TrOCR training.

## Limitations / privacy
- Pillow renderer: Bengali shaping imperfect (no raqm) — HTML/Chromium path gives exact shaping.
- No real PII: all names/addresses/phones/NIDs are random-but-plausible fakes.
- Proxy real set is NOT real — genuine-scan evaluation still required before production claims.
