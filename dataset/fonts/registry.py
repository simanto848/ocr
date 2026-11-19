"""Font registry: single source of truth. Never hard-code font paths elsewhere."""
from __future__ import annotations
import json, os
from pathlib import Path
from dataclasses import dataclass, field

ROOT = Path(os.environ.get("OCR_ROOT", str(Path(__file__).resolve().parents[2])))
FONTS_DIR = Path(os.environ.get("FONTS_DIR", str(ROOT / "fonts")))
REGISTRY_JSON = FONTS_DIR / "registry.json"

@dataclass
class FontEntry:
    key: str
    path: str
    family: str = ""
    language: list = field(default_factory=list)
    weights: list = field(default_factory=list)
    source: str = "local"

class FontRegistry:
    def __init__(self, registry_path: Path | None = None):
        self.path = Path(registry_path or REGISTRY_JSON)
        self.entries: dict[str, FontEntry] = {}
        self.fallback_log: list[dict] = []
        if self.path.exists():
            self.load()

    def load(self):
        data = json.loads(self.path.read_text())
        for k, v in data.get("fonts", {}).items():
            self.entries[k] = FontEntry(key=k, path=v.get("path", ""),
                family=v.get("family", k), language=v.get("language", []),
                weights=v.get("weights", ["regular"]), source=v.get("source", "local"))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"fonts": {k: {"path": e.path, "family": e.family,
                "language": e.language, "weights": e.weights, "source": e.source}
                for k, e in self.entries.items()}}
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def register(self, key, path, family="", language=None, weights=None, source="local"):
        self.entries[key] = FontEntry(key, path, family or key,
            language or [], weights or ["regular"], source)

    def get(self, language="en", family=None, weight="regular", size=32):
        """Return (font_path, metadata, fallback_record|None). Never raises on missing font."""
        from PIL import ImageFont
        # 1. exact family match
        if family and family in self.entries:
            e = self.entries[family]
            p = self._resolve(e.path)
            if p:
                return self._load(p, size, e, None)
        # 2. any font supporting language
        cands = [e for e in self.entries.values() if language in e.language or "mixed" in e.language]
        if not cands:
            cands = list(self.entries.values())
        for e in cands:
            p = self._resolve(e.path)
            if p:
                fb = None if (family is None or e.key == family) else {
                    "requested": {"language": language, "family": family, "weight": weight},
                    "used": e.key, "reason": "family-unavailable-or-weight-fallback"}
                if fb:
                    self.fallback_log.append(fb)
                return self._load(p, size, e, fb)
        # 3. ultimate fallback: PIL default (recorded)
        fb = {"requested": {"language": language, "family": family, "weight": weight},
              "used": "pil_default", "reason": "no-ttf-found"}
        self.fallback_log.append(fb)
        return ImageFont.load_default(), {"key": "pil_default", "path": ""}, fb

    def _resolve(self, p: str):
        if not p:
            return None
        pp = Path(p)
        if not pp.is_absolute():
            pp = FONTS_DIR / pp if not str(pp).startswith(str(ROOT)) else pp
            # also try relative to ROOT
            if not pp.exists():
                pp = ROOT / p
        return str(pp) if pp.exists() else None

    def _load(self, path, size, entry, fb):
        from PIL import ImageFont
        try:
            font = ImageFont.truetype(path, size=size)
        except Exception:
            font = ImageFont.load_default()
            fb = {"requested": entry.key, "used": "pil_default", "reason": "truetype-load-failed"}
            self.fallback_log.append(fb)
        return font, {"key": entry.key, "path": path, "family": entry.family}, fb
