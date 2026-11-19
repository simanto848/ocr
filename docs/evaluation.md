# Evaluation & hard-example mining

```bash
python -m evaluation.evaluate --model base --dataset data/v001 --split test --level line
python -m evaluation.evaluate --checkpoint checkpoints/lines_small_full/best --dataset data/v001
python -m evaluation.mine_hard_examples --checkpoint <ckpt> --dataset data/v001
```

Metrics: CER/WER (raw + NFC/whitespace-normalized), EM, per-language/type/difficulty,
`evaluation_report.json/html` + `failure_gallery/`. Mining reweights failing
fonts/languages/types into `configs/hard_examples.yaml` for the next dataset version.
Real set: `--dataset real_world_test`. See `DOMAIN_GAP_REPORT.md`.
