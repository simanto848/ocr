"""Model helpers + param budget enforcement (<0.5B)."""
import env_bootstrap  # noqa: F401  (must be first: pins all caches to external drive)
from transformers import TrOCRProcessor, VisionEncoderDecoderModel


def count_params(model) -> int:
    return sum(p.numel() for p in model.parameters())


def load_recognizer(model_id: str, device: str = "cpu"):
    processor = TrOCRProcessor.from_pretrained(model_id)
    model = VisionEncoderDecoderModel.from_pretrained(model_id)
    model.to(device)
    n = count_params(model)
    print(f"[recognizer] {model_id}: {n/1e6:.1f}M params")
    assert n < 500_000_000, f"Recognizer {n} exceeds 0.5B budget!"
    return processor, model


def check_total_budget(recognizer_n: int, detector_n: int, max_params: int = 500_000_000):
    total = recognizer_n + detector_n
    print(f"[budget] recognizer={recognizer_n/1e6:.1f}M + detector={detector_n/1e6:.1f}M = {total/1e6:.1f}M (limit {max_params/1e6:.0f}M)")
    assert total < max_params, f"Total {total} exceeds {max_params}!"
    return total
