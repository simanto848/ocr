# real_world_test

Synthetic proxy set (heavy degradation, held-out seeds).
To add genuine scans: put PNGs in `images/`, append `images/<f>\t<text>` rows to
`ground_truth.tsv`, and evaluate with:

  python -m evaluation.evaluate --checkpoint <ckpt> --dataset real_world_test --split test

NEVER include this directory in training data.
