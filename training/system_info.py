"""python -m training.system_info: GPU/VRAM/CUDA/torch/bf16. Fails loudly without CUDA for big jobs."""
import sys as _sys
from pathlib import Path as _Path
_r = _Path(__file__).resolve().parent
while not (_r / "src" / "env_bootstrap.py").exists():
    if _r == _r.parent:
        break
    _r = _r.parent
_sys.path.insert(0, str(_r / "src"))
import env_bootstrap  # noqa: F401,E402  (pins all caches to external drive)
import torch

def main():
    print(f"torch={torch.__version__} cuda={torch.cuda.is_available()} mps={torch.backends.mps.is_available()}")
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            p = torch.cuda.get_device_properties(i)
            print(f"gpu{i}: {p.name} vram={p.total_memory/1e9:.1f}GB bf16={p.major>=8}")
    else:
        print("NOTE: no CUDA (M4 MPS available). Large base-model jobs should run on GPU server.")

if __name__ == "__main__":
    main()
