"""python -m training.train --config configs/training.yaml [--steps N] [--model-id X]
Wraps src/train.py logic + YAML config + LoRA (PEFT) + experiment tracking + GPU guard.
92% shared with src/train.py (imports Dataset + count_params from src/ — EXTEND not rebuild).
"""
from __future__ import annotations
import argparse, json, os, sys, time, subprocess
from pathlib import Path
import yaml
import sys as _sys
from pathlib import Path as _Path
_r = _Path(__file__).resolve().parent
while not (_r / "src" / "env_bootstrap.py").exists():
    if _r == _r.parent:
        break
    _r = _r.parent
_sys.path.insert(0, str(_r / "src"))
import env_bootstrap  # noqa: F401,E402  (pins all caches to external drive)

ROOT = Path(os.environ.get("OCR_ROOT", str(Path(__file__).resolve().parents[1])))

def load_cfg(p):
    return yaml.safe_load(Path(p).read_text()) if p and Path(p).exists() else {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/training.yaml")
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--output-dir", default=None)
    a = ap.parse_args()
    cfg = load_cfg(ROOT / a.config if not str(a.config).startswith(str(ROOT)) else a.config)
    tr, mo, ds, lo, out = cfg.get("training", {}), cfg.get("model", {}), cfg.get("dataset", {}), cfg.get("lora", {}), cfg.get("output", {})
    model_id = a.model_id or mo.get("name", "microsoft/trocr-base-printed")
    steps = a.steps or tr.get("max_steps", 800)
    outdir = Path(a.output_dir or out.get("dir", "checkpoints/exp001"))
    if not str(outdir).startswith(str(ROOT)):
        outdir = ROOT / outdir

    sys.path.insert(0, str(ROOT / "src"))
    import torch
    from torch.utils.data import DataLoader, random_split
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel, get_linear_schedule_with_warmup
    from tqdm import tqdm
    from data import OCRTsvDataset
    from model import count_params

    # GPU guard: warn (don't hard-fail on M4, but refuse silent giant CPU jobs)
    dev = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cpu" and steps > 200:
        print("REFUSE: >200 steps on CPU. Use GPU/MPS or reduce --steps."); sys.exit(3)
    print(f"device={dev} model={model_id} steps={steps} lora={lo.get('enabled', False)}")

    torch.manual_seed(tr.get("seed", 42))
    tsv = ROOT / ds.get("train", "data/v001/train.tsv")
    val_tsv = ROOT / ds.get("validation", "data/v001/val.tsv")
    img_root = ROOT / ds.get("images_root", "data/v001")
    if not tsv.exists():  # fallback to legacy synthetic (backwards compat)
        tsv = ROOT / "data/synthetic/labels.tsv"; img_root = ROOT / "data/synthetic"; val_tsv = None

    proc = TrOCRProcessor.from_pretrained(model_id)
    model = VisionEncoderDecoderModel.from_pretrained(model_id)
    n = count_params(model)
    print(f"params={n/1e6:.1f}M (limit {mo.get('max_params', 500_000_000)/1e6:.0f}M)")
    assert n < mo.get("max_params", 500_000_000)
    model.config.decoder_start_token_id = proc.tokenizer.cls_token_id
    model.config.pad_token_id = proc.tokenizer.pad_token_id
    model.config.vocab_size = model.config.decoder.vocab_size
    if tr.get("freeze_encoder"):
        for p in model.encoder.parameters():
            p.requires_grad = False
    use_lora = bool(lo.get("enabled", False))
    if use_lora:
        try:
            from peft import LoraConfig, get_peft_model, TaskType
            # VisionEncoderDecoderConfig nests vocab_size; peft expects top-level
            try:
                _v = model.config.decoder.vocab_size
                model.config.vocab_size = _v
            except Exception:
                pass
            lc = LoraConfig(r=lo.get("rank", 16), lora_alpha=lo.get("alpha", 32),
                            lora_dropout=lo.get("dropout", 0.05),
                            target_modules=lo.get("target_modules", ["q_proj", "v_proj"]))
            model = get_peft_model(model, lc)
            model.print_trainable_parameters()
        except Exception as e:
            print(f"LoRA unavailable ({type(e).__name__}: {str(e)[:150]}); continuing full fine-tune")
            use_lora = False
    model.to(dev).train()

    bs = tr.get("batch_size", 8); accum = tr.get("gradient_accumulation_steps", 2)
    ds_full = OCRTsvDataset(str(tsv), str(img_root), proc, 128)
    val_ds = OCRTsvDataset(str(val_tsv), str(img_root), proc, 128) if val_tsv and Path(val_tsv).exists() else None
    if val_ds is None:
        nV = max(1, int(len(ds_full) * 0.1))
        ds_full, val_ds = random_split(ds_full, [len(ds_full) - nV, nV],
            generator=torch.Generator().manual_seed(tr.get("seed", 42)))
    tl = DataLoader(ds_full, batch_size=bs, shuffle=True, num_workers=0)
    vl = DataLoader(val_ds, batch_size=bs, num_workers=0)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                            lr=tr.get("learning_rate", 2e-5), weight_decay=tr.get("weight_decay", 0.01))
    sch = get_linear_schedule_with_warmup(opt, int(steps * tr.get("warmup_ratio", 0.05)), steps)
    outdir.mkdir(parents=True, exist_ok=True)
    exp_id = f"exp_{int(time.time())}"

    def save_ckpt(path):
        # PEFT save_pretrained breaks on VisionEncoderDecoderConfig (no top-level
        # vocab_size on fresh hub config) → fall back to raw state_dict + note.
        path = Path(path); path.mkdir(parents=True, exist_ok=True)
        try:
            model.save_pretrained(str(path))
        except Exception as e:
            print(f"save_pretrained failed ({type(e).__name__}), saving state_dict instead")
            torch.save(model.state_dict(), str(path / "adapter_state.pt"))
            (path / "SAVE_NOTE.txt").write_text(
                f"save_pretrained failed: {e}\nLoad base {model_id} then load_state_dict(strict=False).\n")
        try:
            proc.save_pretrained(str(path))
        except Exception as e:
            print(f"processor save failed: {e}")
    best, patience, bad = float("inf"), tr.get("early_stopping_patience", 3), 0
    step = ostep = 0; run = 0.0
    it = iter(tl); pbar = tqdm(total=steps, desc="train")
    metrics_log = []
    while ostep < steps:
        try:
            b = next(it)
        except StopIteration:
            it = iter(tl); b = next(it)
        loss = model(pixel_values=b["pixel_values"].to(dev), labels=b["labels"].to(dev)).loss / accum
        loss.backward(); run += loss.item() * accum; step += 1
        if step % accum == 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sch.step(); opt.zero_grad(); ostep += 1; pbar.update(1)
            if ostep % 50 == 0:
                print(f"step {ostep} loss {run/50:.4f}"); run = 0.0
            if ostep % 200 == 0 or ostep == steps:
                model.eval(); tot = c = 0
                with torch.no_grad():
                    for bb in vl:
                        tot += model(pixel_values=bb["pixel_values"].to(dev), labels=bb["labels"].to(dev)).loss.item(); c += 1
                        if c >= 10: break
                v = tot / max(1, c); model.train()
                print(f"[eval] {ostep} val_loss {v:.4f}")
                metrics_log.append({"step": ostep, "val_loss": v})
                if v < best:
                    best, bad = v, 0
                    save_ckpt(outdir / "best")
                else:
                    bad += 1
                    if bad >= patience:
                        print(f"early-stop at {ostep} (best {best:.4f})"); break
    pbar.close()
    save_ckpt(outdir / "final")
    meta = {"experiment_id": exp_id, "model": model_id, "params": n, "lora": use_lora,
            "steps": ostep, "best_val": best, "config": cfg, "device": dev,
            "git": subprocess.getoutput("git rev-parse --short HEAD 2>/dev/null") or "n/a"}
    (outdir / "experiment.json").write_text(json.dumps(meta, indent=2))
    (outdir / "metrics.json").write_text(json.dumps(metrics_log, indent=2))
    print(f"DONE best_val={best:.4f} → {outdir} ({exp_id})")

if __name__ == "__main__":
    main()
