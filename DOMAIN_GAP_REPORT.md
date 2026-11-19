# DOMAIN_GAP_REPORT.md — synthetic vs real

## Method
Compared v001 test (200 dpi, tier mix) vs `real_world_test` proxy (150 dpi, forced-heavy,
held-out seeds) with the same checkpoint (`checkpoints/lines_small_full/best`), line level.

| set | n | CER | WER |
|---|---|---|---|
| v001 test (synthetic) | 60 | 0.709 | 0.875 |
| real proxy (heavy/150dpi) | 12 | 0.720 | 0.909 |

No collapse under heavy degradation (ΔCER +0.011) — degradation pipeline generalizes within
its own family. This does NOT prove real-world readiness (see below).

## Known unrealistic characteristics
1. **Shaping**: Pillow path without raqm breaks some Bengali conjuncts (`juktakkhor` render as
   dotted fragments). The model may learn broken glyph shapes. Mitigation: HTML/Chromium
   renderer (`dataset/rendering/html_renderer.py`) for production volumes.
2. **Backgrounds**: flat white only — no desk texture, shadows beyond vignette, folds, stamps
   overlapping text, coffee stains, ruled paper.
3. **Capture**: synthetic perspective/blur/noise approximates phone capture but lacks rolling
   shutter, moiré, glare, multi-illuminant color casts.
4. **Layout**: 10 templates with constrained randomization; real government forms have far
   longer tails (nested tables, tiny footnotes ≤8pt, vertical text, seals over text).
5. **Worst groups** (from hard mining): invoices/tables CER 0.94, receipts 0.77 — numeric+
   tabular content is the current frontier; small fonts (<14pt) underrepresented in errors
   only because line-crop eval filters tiny boxes (<8px).

## What to collect next (real)
50–200 genuine scans/photos per priority type (invoice, gov_form, receipt), transcribed once
by humans into `real_world_test/ground_truth.tsv` format. Re-run `evaluation.evaluate`
on `--dataset real_world_test`; if real CER exceeds synthetic by >0.15, add the missing
characteristic (background/texture/layout) to the generator before scaling to 50k.
