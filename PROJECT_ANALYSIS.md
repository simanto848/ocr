# PROJECT_ANALYSIS.md — OCR pipeline audit (external-drive project)

## 1. Current architecture
```
<repo-root>
├── .venv/                 # all packages (torch 2.14, transformers 4.46.3, doctr, opencv)
├── .cache/                # HF_HOME, DOCTR_CACHE_DIR, pip, torch — all external
├── src/
│   ├── config.py          # TRAIN_CONFIG, INFER_CONFIG, RECOGNIZER_ID=trocr-base-printed (334M)
│   ├── model.py           # count_params, load_recognizer, check_total_budget (<500M assert)
│   ├── data.py            # OCRTsvDataset: TSV images/<f>\t<text>, processor → pixel_values+labels
│   ├── make_synthetic.py  # ⚠️ PIL bitmap font, 8 hardcoded English strings, 600x80 lines
│   ├── train.py           # TrOCR fine-tune, MPS, freeze-encoder, val split 5%, save best/final
│   ├── infer.py           # doctr db_mobilenet_v3_large (4.2M) detect → TrOCR recognize, line_mode
│   ├── detect.py          # doctr detection_predictor, handles list/dict new API
│   └── evaluate.py        # jiwer CER/WER/EM on TSV pairs
├── data/synthetic/        # 1000 bitmap lines + labels.tsv
├── checkpoints/           # trocr-small-ocr/best (61.6M, 200 steps), trocr-small-ocr-800/best (800 steps)
├── outputs/, logs/
├── env.sh                 # OCR_ROOT, HF_HOME, DOCTR_CACHE_DIR, XDG_CACHE_HOME → external
└── requirements.txt       # transformers==4.46.3 (v5 breaks TrOCR), numpy==1.26.4
```

## 2. Existing data flow
`make_synthetic.render_line()` → PIL `ImageDraw.text` **without font** → `ImageFont.load_default()` bitmap →
`data/synthetic/images/synth_*.png` + `labels.tsv` (`images/<f>\t<text>`) →
`OCRTsvDataset` → processor(384px) → `pixel_values, labels(-100 pad)` → DataLoader.

## 3. Existing model flow
Recognizer `microsoft/trocr-base-printed` 333.9M (ViT-Base 86M + 12-layer decoder) or
`trocr-small-printed` 61.6M (DeiT-tiny + 6-layer decoder). Detector doctr `db_mobilenet_v3_large`
4.2M. Totals: 65.8M (fast) / 338.1M (accurate), both <500M asserted in `infer.py`.

## 4. Existing generator flow
Single function, no layout, no fonts, no tables, no degradation, no bboxes, no metadata,
no splits, no validation. Random choice from 8 English strings + `Ref:NNNNN`.

## 5. Existing training flow
`src/train.py: train()` → load processor+model → optional freeze encoder → 95/5 random split →
AdamW 5e-5 + linear warmup → grad_accum 2 → eval_every/save_every 200 → save best/final.
No LoRA, no mixed precision config, no experiment tracking, no curriculum, no hard mining.
M4 MPS: small ~0.6s/step, base ~35s/step.

## 6. Existing evaluation flow
`src/evaluate.py`: TSV pred vs gt → jiwer CER/WER/EM. No normalization options, no per-language
split, no field/table metrics, no failure gallery, no real-world set.

## 7. Problems discovered
1. **P1 bitmap font**: `make_synthetic.py:23` uses default bitmap → ugly glyphs, zero Bengali,
   pretrained CER ~1.0 on it; fine-tuned CER 0.37 (still poor). Root cause of limitation.
2. **P1 no shaping**: Pillow `raqm=False` (checked) → Bengali conjuncts (juktakkhor, kar, fola)
   would break even with TTF. Need HTML/Chromium (HarfBuzz) path.
3. **P1 English-only**: zero bn content, no mixed docs.
4. **P2 single layout**: 600x80 line only; no A4/pages/tables/forms/invoices/receipts/certs/legal.
5. **P2 no degradation**: clean only → real-domain gap (camera, blur, lighting, JPEG).
6. **P2 labels only `image→text`**: no word/line/block bboxes, no tables/KV, bboxes not updated
   under geometry (detect.py only used at inference).
7. **P3 no validation/stats/splits/versioning**: silent corruption possible, leakage possible.
8. **P3 no LoRA/QLoRA, no GPU guard, no bf16, no experiment tracking, no early stopping on CER.**
9. Hard-coded: TEXTS list, image size, augmentation (none), dataset size, paths in code.
10. `transformers==4.46.3` pinned (v5 breaks TrOCR processor) — must keep.

## 8. Files needing modification
- `src/make_synthetic.py` — keep for backwards compat, mark deprecated, delegate line-gen to
  new `dataset/` for simple cases.
- `src/train.py` — add LoRA + YAML config + experiment meta, keep CLI flags working.
- `src/evaluate.py` — add normalization + per-language metrics, keep TSV interface.
- `src/data.py` — add manifest/WebDataset-style loader alongside TSV loader (no break).
- `requirements.txt`, `env.sh` — add peft, pyyaml, playwright, fonttools; add
  `PLAYWRIGHT_BROWSERS_PATH`, `FONTS_DIR`.
- `README.md` — document new pipeline.

## 9. Files needing creation
```
dataset/__init__.py, __main__ hooks (generate/validate/stats/preview)
dataset/fonts/{registry.py,scanner.py,selector.py,scan.py}
dataset/content/generators.py (bn/en names, addresses, phones, dates, invoices, currency)
dataset/templates/{base,invoice,receipt,certificate,form,legal,application,article,academic,mixed}.py
dataset/rendering/{engine.py,html_renderer.py,pillow_renderer.py}
dataset/augmentation/degrader.py
dataset/annotations/{schema.py,generator.py}
dataset/validation/{validator.py,duplicates.py,statistics.py}
dataset/{generate.py,validate.py,stats.py,preview.py}
training/{train.py,config.py,system_info.py}
evaluation/{evaluate.py,metrics.py,mine_hard_examples.py}
configs/{dataset.yaml,augmentation.yaml,training.yaml,fonts.yaml}
fonts/registry.json (+ downloaded TTFs)
tests/test_*.py
docs/*.md, PROJECT_ANALYSIS.md (this), DATASET_CARD.md, DOMAIN_GAP_REPORT.md, TRAINING_REPORT.md
```

## 10. Proposed architecture
```
ContentGen (bn/en deterministic) → LayoutEngine (10 templates, constrained randomization)
 → FontRegistry (TTF/OTF, bn+en, fallback logged) → HTML/CSS → Chromium/Playwright → PDF/300dpi PNG
 ↘ Pillow-TTF fallback (English/simple) 
 → Degrader (rotation/perspective/blur/noise/lighting/JPEG/resolution, bbox-preserving)
 → GT generator (from structured doc, never OCR) → Validator → Balancer → vNNN splits (80/10/10, seed 42)
 → TrOCR-338M (+LoRA) → synth eval + real eval → error groups → hard-config → vNNN+1 → retrain
```

## 11. Migration strategy
1. Do not delete `src/*`; new `dataset/`, `training/`, `evaluation/` import from `src/` where
   sensible (`count_params`, `OCRTsvDataset`, jiwer wrappers).
2. Font abstraction first; Pillow renderer switches from `load_default()` to registry TTF
   immediately (backwards-compatible output paths).
3. HTML renderer added as preferred path; Pillow kept as fallback for environments without Chromium.
4. New dataset versions under `data/vNNN/` with `manifest.json`; old `data/synthetic/` untouched.
5. Training CLI `python -m training.train` wraps `src/train.py:train()` + LoRA via PEFT when
   `--config` enables it; old `python src/train.py` keeps working.
6. Acceptance commands implemented as `__main__` modules; each tested on 1k before 10k/50k.
