# Architecture

`PROJECT_ANALYSIS.md` (audit) → this pipeline. Legacy `src/` untouched and working;
new packages import from it (EXTEND, don't rebuild).

```
dataset/content → dataset/templates → dataset/fonts → dataset/rendering
      → dataset/augmentation → annotations → dataset/validation
      → data/vNNN (+lines/) → training/train.py → evaluation/* → hard config → vNNN+1
```

- Fonts: `dataset/fonts/` (registry/scanner/selector). No hard-coded paths.
- Rendering: `dataset/rendering/` — Pillow-TTF default, HTML/Chromium for exact shaping.
- Degradation: `dataset/augmentation/degrader.py`, bbox-preserving, YAML probabilities.
- Splits/versioning: `dataset/generate.py` → `manifest.json`, `splits.json`, never overwrite.
- Training: `training/train.py` (YAML + LoRA + experiment.json). Eval: `evaluation/`.
