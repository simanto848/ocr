# Dataset generation

```bash
source ./env.sh
python -m dataset.fonts.scan
python -m dataset.generate --count 1000 --output data/v001 --seed 42
python -m dataset.export_lines --dataset data/v001
python -m dataset.validate --dataset data/v001
python -m dataset.stats --dataset data/v001
python -m dataset.preview --dataset data/v001 --count 20
```

Stages: 1k inspect → 10k validate → 50k baseline → 100k+ production (`--count` any size,
`--config` overrides distributions; existing versions refuse overwrite without `--force`).
Second cycle: `python -m dataset.generate --config configs/hard_examples.yaml --output data/v011`.
