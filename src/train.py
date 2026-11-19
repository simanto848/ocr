"""Fine-tune TrOCR (<0.5B) on external drive. Uses MPS on M4, else CPU."""
import env_bootstrap  # noqa: F401  (must be first: pins all caches to external drive)
import os, argparse, math, random
from pathlib import Path
import torch
from torch.utils.data import DataLoader, random_split
from transformers import TrOCRProcessor, VisionEncoderDecoderModel, get_linear_schedule_with_warmup
from tqdm import tqdm

from config import TRAIN_CONFIG
from data import OCRTsvDataset
from model import count_params

def get_device():
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"

def train(args):
    root = Path(os.environ.get("OCR_ROOT", str(Path(__file__).resolve().parents[1])))
    cfg = TRAIN_CONFIG.copy()
    if args.output_dir: cfg["output_dir"] = args.output_dir
    if args.steps: cfg["max_steps"] = args.steps
    if args.model_id: cfg["recognizer_id"] = args.model_id

    out = Path(cfg["output_dir"]); out.mkdir(parents=True, exist_ok=True)
    device = get_device()
    print(f"Device: {device}")

    processor = TrOCRProcessor.from_pretrained(cfg["recognizer_id"])
    model = VisionEncoderDecoderModel.from_pretrained(cfg["recognizer_id"])
    n = count_params(model)
    print(f"Params: {n/1e6:.1f}M (budget 500M)")
    assert n < 500_000_000
    model.config.decoder_start_token_id = processor.tokenizer.cls_token_id
    model.config.pad_token_id = processor.tokenizer.pad_token_id
    model.config.vocab_size = model.config.decoder.vocab_size
    if getattr(args, "freeze_encoder", False):
        for p in model.encoder.parameters():
            p.requires_grad = False
        print("Froze ViT encoder (decoder-only fine-tune, ~2x faster on M4)")
    model.to(device)
    model.train()

    # Data: synthetic + optional custom TSV
    synth_tsv = root / "data" / "synthetic" / "labels.tsv"
    synth_root = root / "data" / "synthetic"
    if not synth_tsv.exists():
        from make_synthetic import make_synthetic
        make_synthetic(str(synth_root), n=1000)

    tsv = args.train_tsv or str(synth_tsv)
    img_root = args.images_root or str(synth_root)
    ds = OCRTsvDataset(tsv, img_root, processor, cfg["max_target_length"])
    val_n = max(1, int(len(ds) * 0.05))
    train_ds, val_ds = random_split(ds, [len(ds) - val_n, val_n],
        generator=torch.Generator().manual_seed(cfg["seed"]))

    train_loader = DataLoader(train_ds, batch_size=cfg["batch_size"], shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=cfg["batch_size"], num_workers=0)

    opt = torch.optim.AdamW(model.parameters(), lr=cfg["lr"])
    total_opt_steps = math.ceil(len(train_loader) / cfg["grad_accum"]) * 100000  # upper bound
    # simpler: constant schedule sized to max_steps
    sched = get_linear_schedule_with_warmup(opt, int(cfg["max_steps"]*cfg["warmup_ratio"]), cfg["max_steps"])

    step, opt_step = 0, 0
    running = 0.0
    model.zero_grad()
    pbar = tqdm(total=cfg["max_steps"], desc="train")
    train_iter = iter(train_loader)
    best_val = float("inf")
    while opt_step < cfg["max_steps"]:
        try:
            batch = next(train_iter)
        except StopIteration:
            train_iter = iter(train_loader)
            batch = next(train_iter)
        pv = batch["pixel_values"].to(device)
        labels = batch["labels"].to(device)
        out_m = model(pixel_values=pv, labels=labels)
        loss = out_m.loss / cfg["grad_accum"]
        loss.backward()
        running += loss.item() * cfg["grad_accum"]
        step += 1
        if step % cfg["grad_accum"] == 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            opt_step += 1
            pbar.update(1)
            if opt_step % 50 == 0:
                print(f"step {opt_step} loss {running/50:.4f} lr {sched.get_last_lr()[0]:.2e}")
                running = 0.0
            if opt_step % cfg["eval_every"] == 0:
                vl = evaluate(model, val_loader, device)
                print(f"[eval] step {opt_step} val_loss {vl:.4f}")
                if vl < best_val:
                    best_val = vl
                    model.save_pretrained(str(out / "best"))
                    processor.save_pretrained(str(out / "best"))
                    print(f"saved best -> {out/'best'}")
            if opt_step % cfg["save_every"] == 0:
                model.save_pretrained(str(out / f"step-{opt_step}"))
                processor.save_pretrained(str(out / f"step-{opt_step}"))
    pbar.close()
    model.save_pretrained(str(out / "final"))
    processor.save_pretrained(str(out / "final"))
    print(f"Done. best_val={best_val:.4f} saved to {out}")

@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    tot, cnt = 0.0, 0
    for b in loader:
        loss = model(pixel_values=b["pixel_values"].to(device), labels=b["labels"].to(device)).loss
        tot += loss.item(); cnt += 1
        if cnt >= 20: break
    model.train()
    return tot / max(1, cnt)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-tsv", default=None)
    ap.add_argument("--images-root", default=None)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--freeze-encoder", action="store_true", help="freeze ViT, train decoder only (faster)")
    ap.add_argument("--batch-size", type=int, default=None)
    args = ap.parse_args()
    if args.batch_size:
        TRAIN_CONFIG["batch_size"] = args.batch_size
    train(args)
