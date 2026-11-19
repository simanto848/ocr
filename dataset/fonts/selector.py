"""FontSelector: deterministic language-aware font choice with distribution control."""
from __future__ import annotations
import random
from .registry import FontRegistry

# Configurable distribution (overridden by configs/fonts.yaml)
DEFAULT_DIST = {
    "bn": [("noto_sans_bengali", 0.30), ("noto_serif_bengali", 0.15), ("hind_siliguri", 0.15)],
    "en": [("inter", 0.25), ("roboto", 0.25), ("liberation_serif", 0.10)],
}

class FontSelector:
    def __init__(self, registry: FontRegistry, dist: dict | None = None, seed: int = 42):
        self.reg = registry
        self.dist = dist or DEFAULT_DIST
        self.rng = random.Random(seed)

    def pick(self, language: str, role: str = "body"):
        """role: heading|body|mono. Returns (pil_font, meta, fallback)."""
        lang = "bn" if language.startswith("bn") else "en"
        opts = self.dist.get(lang) or self.dist.get("en")
        # fuzzy-match registry keys (scan keys vary by system)
        cands = []
        for want, w in opts:
            for key in self.reg.entries:
                kl, wl = key.lower(), want.lower().replace(" ", "")
                if wl in kl or kl in wl:
                    cands.append((key, w))
                    break
        if not cands:  # any font for language
            cands = [(e.key, 1.0) for e in self.reg.entries.values()
                     if lang in e.language] or [(e.key, 1.0) for e in self.reg.entries.values()]
        keys, ws = zip(*cands)
        fam = self.rng.choices(keys, weights=ws, k=1)[0]
        size = {"heading": self.rng.choice([28, 32, 36]), "body": self.rng.choice([18, 20, 24]),
                "small": self.rng.choice([12, 14, 16])}.get(role, 20)
        weight = "bold" if role == "heading" and self.rng.random() < 0.7 else "regular"
        return self.reg.get(language=lang, family=fam, weight=weight, size=size)
