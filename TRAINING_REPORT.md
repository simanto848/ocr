# TRAINING_REPORT.md

## Experiments (M4 MPS, external drive)
| id | base | data | method | steps | train loss | val loss | test CER (lines) |
|---|---|---|---|---|---|---|---|
| base-zero-shot | trocr-base-printed 334M | — | none | 0 | — | — | 0.838 (n=30) |
| small-zero-shot | trocr-small-printed 62M | — | none | 0 | — | — | 1.030 (n=100) |
| lines_small_full | small 62M | v001 lines 6,093 | full FT, lr 3e-5 | 600 | 5.1→3.9 | 2.49→1.79 | 0.948 (n=100) / 0.709 (n=60 pages) |
| lines_small_lora | small 62M | v001 lines 6,093 | LoRA r16 + frozen enc, lr 1e-4 | 200 | 29.3→17.2 | 8.12 | n/a (adapter) |
| cycle2_hard | small 62M (from lines_small_full/best) | v011-hard lines 8,934 | full FT, lr 2e-5 | 200 | 4.04→3.72 | 1.778 | 0.926 (n=100, was 0.948) |
| v010_small_clean | small 62M (from scratch HF) | v010 lines 44,842 | full FT, lr 3e-5 | 800 | →3.34 | **1.499** | **0.958** (n=100) + zero Ref: artifacts on real cert |

Configs: `configs/training_lines.yaml` (full), `configs/training_lora.yaml` (LoRA).
Artifacts: `checkpoints/<exp>/{best,final,experiment.json,metrics.json}` — never overwritten,
config + seed + metrics stored per experiment.

## Findings
1. Fine-tuning works: outputs shift from English hallucination to Bengali fragments;
   val loss −28%, CER −0.08 at only ~1.5 epochs. Under-training is the limiter, not capacity.
2. **Layout was the visible bug, not just accuracy** (web UI, Sep 2026): word boxes joined
   with `\n` stacked one word per line. Fixed in `src/layout.py` — words→lines→blocks;
   line crops also recognize better than word crops. Verified on the real certificate page.
3. **`Ref:XXXX` hallucinations root-caused**: legacy `src/make_synthetic.py` appended
   `" Ref:NNNNN"` to 30% of samples → `trocr-small-ocr-800` learned the pattern and emits
   it on real docs. Suffix removed; clean retrain `v010_small_clean` (v010 lines, no Ref:)
   in progress. Models trained on template-pool text (lines_small_full/cycle2) instead
   regurgitate memorized sentences — TR needs diverse content, not more steps alone.
2. LoRA path functions (loss decreases) but PEFT `save_pretrained` is incompatible with
   `VisionEncoderDecoderConfig` → adapters saved as `adapter_state.pt` + note; full FT is
   the supported path for TrOCR until PEFT handles encoder-decoder configs. QLoRA not
   attempted (no CUDA 4-bit kernels on MPS).
3. Mixed precision: bf16 requested; MPS trains fp32 (no bf16) — GPU server will use bf16.
4. Memorization beats under-training as the next bottleneck: 9-sentence template pools get
   regurgitated on unseen docs. Content pool expanded 9→36 sentences
   (`dataset/content/generators.py`); future datasets regenerate from it. Web/CLI default
   is now `v010_small_clean/best` (no Ref:, best val, best CER).
4. No real-domain overfitting signal: synthetic 0.709 vs proxy-real 0.720 (Δ +0.011).

## Next (second cycle, GPU)
1. Finish v010 10k → export lines (~75k) → curriculum: clean-only 1k steps → full-mix 4k steps,
   base-338M, batch 8×accum 4, bf16, LoRA-off.
2. Generate hard set from `configs/hard_examples.yaml` (invoice/gov_form/bn-heavy, 2k) →
   mix 1:1 with v010 lines → 1k-step continuation from best.
3. Target: line CER < 0.15 synthetic, < 0.25 real scans before claiming production.
