# Troubleshooting

- `TRANSFORMERS_CACHE ... not writable` / doctr downloading to internal disk →
  fixed: every entry point auto-imports `src/env_bootstrap.py`, which pins all
  caches to the external drive even without `source ./env.sh`. Still source it
  for the right `python`/`pip` on PATH.
- `RuntimeError: DOCTR_CACHE_DIR must point inside OCR_ROOT` → you bypassed the
  bootstrap (e.g. `python -c "from detect import ..."` without repo on path).
  Run the documented CLI commands instead.
- Pillow Bengali looks dotted → expected without raqm; use HTML renderer for print runs.
- `python -m dataset.generate` refuses → output exists; use `--force` or new `data/vNNN`.
- TrOCR page-level CER ≈ 1.0 → evaluate/train on `lines/` exports, not full pages.
- LoRA `save_pretrained ... vocab_size` error → handled: `adapter_state.pt` + note; full FT unaffected.
- MPS has no bf16 → trains fp32; bf16 activates on CUDA.
- `python -m training.train` refuses on CPU >200 steps → use GPU or fewer steps.
