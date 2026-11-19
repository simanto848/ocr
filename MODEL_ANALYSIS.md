# MODEL_ANALYSIS.md — 338M base model audit

## Identity
- `microsoft/trocr-base-printed`: **333,921,792 params** (measured, <500M budget).
- Architecture: `VisionEncoderDecoderModel` — ViT-Base encoder (12 layers, 768 hidden,
  16×16 patches, 384px) + TrOCR causal decoder (12 layers, d_model 1024, 16 heads,
  vocab 50265, RoBERTa-derived tokenizer).
- Small sibling `trocr-small-printed`: 61,596,672 params (DeiT-tiny encoder + 6-layer decoder).

## It is NOT a Bengali OCR model
- Pretrained on English printed/handwritten lines (IAM + synthetic). Tokenizer is
  English BPE: `বাংলাদেশ সরকার` → 17 tokens via byte fallbacks (vs 3 for `Report`).
- Measured baseline on v001 line crops: base CER **0.84**, small CER **1.03** —
  Bengali lines decode as English hallucinations (`GOODER *** FACEBOOK ...`).
- Conclusion: cross-script transfer must be *learned* by fine-tuning. After 600 steps
  full fine-tune (small, lines): CER 1.03 → **0.95** (100-line sample), val loss
  2.49 → 1.79, outputs switch to Bengali-like fragments. Direction correct,
  magnitude needs 5k+ steps on GPU (see TRAINING_REPORT.md).

## Processor / limits
- Input 384×384 (pages downscaled → line-level training/eval required; page-level CER ≈ 1.0).
- `decoder_start_token_id=cls`, `pad_token_id` masked as -100. Max positions 512;
  keep `max_target_length ≤ 128` for lines (Bengali is token-hungry).
- `transformers==4.46.3` pinned: v5 breaks `TrOCRProcessor.from_pretrained`.

## Detector (not the bottleneck)
- doctr `db_mobilenet_v3_large`: **4,183,858 params**. Totals: 65.8M (small) / 338.1M (base).

## Size decision
- 338M capacity is NOT the demonstrated bottleneck — data volume/steps are.
  Do not scale the model before 50k-line curriculum + 5k-step run is measured.
