# Augmentation

`dataset/augmentation/degrader.py` — rotation (±0–2° 80%, ±2–4° 15%, ±4–7° 5%),
perspective (p=0.35), Gaussian blur, Gaussian noise, vignette lighting, JPEG q50–95,
resolution downsample. Tiers: clean 40 / light 30 / moderate 20 / heavy 10.
All geometry ops transform word bboxes. Probabilities: `configs/augmentation.yaml`.
