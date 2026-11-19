# Training

```bash
python -m training.system_info
python -m training.train --config configs/training_lines.yaml        # full FT
python -m training.train --config configs/training_lora.yaml         # LoRA (+fallback save)
```

YAML: model/training(lr, batch, accum, warmup, bf16, freeze, early-stop)/dataset/lora/output.
Refuses >200 steps on CPU. Checkpoints: `{best,final,experiment.json,metrics.json}`.
GPU server: same command, bf16 active, QLoRA optional via peft+bitsandbytes.
Legacy `python src/train.py` still works (bitmap TSV).
