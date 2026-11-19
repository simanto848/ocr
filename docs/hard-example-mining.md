# Hard-example mining

1. Evaluate: `python -m evaluation.evaluate --checkpoint <ckpt> --dataset data/vNNN`
   → `evaluation_report.json` (per-group CER) + `failure_gallery/`.
2. Mine: `python -m evaluation.mine_hard_examples --checkpoint <ckpt>`
   → reweights failing languages/types into `configs/hard_examples.yaml`.
3. Regenerate: `python -m dataset.generate --config configs/hard_examples.yaml --output data/vNNN-hard`.
4. Continue training from `best` on hard lines mixed 1:1 with base lines (curriculum).
5. Current signal: invoices/tables CER 0.94, bn 0.75 vs en 0.62 → hard config boosts
   invoice 0.22/gov_form 0.17/bn 0.42. Second-cycle training planned in TRAINING_REPORT.md.
