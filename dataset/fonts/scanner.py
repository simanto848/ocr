"""Scan font directories → fonts/registry.json (family, style, weight, language)."""
from __future__ import annotations
import os, json
from pathlib import Path

ROOT = Path(os.environ.get("OCR_ROOT", str(Path(__file__).resolve().parents[2])))
FONTS_DIR = Path(os.environ.get("FONTS_DIR", str(ROOT / "fonts")))
SYSTEM_DIRS = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
               "/Library/Fonts", str(Path.home() / "Library" / "Fonts")]

def _lang_hint(path: str, family: str) -> list:
    s = (path + " " + family).lower()
    langs = []
    if any(k in s for k in ["beng", "bangla", "bengali", "hindsiliguri", "baloo da", "kohinoor", "sangam"]):
        langs.append("bn")
    # latin coverage assumed for most
    if not langs or any(k in s for k in ["noto", "inter", "roboto", "liberation", "verdana", "arial", "times", "helvetica"]):
        langs.append("en")
    if "bn" in langs and "en" in langs:
        return ["bn", "en"]
    return langs or ["en"]

def _weight_hint(name: str) -> str:
    n = name.lower()
    for w in ["bold_italic", "bolditalic", "bold", "italic", "medium", "semibold", "light", "thin"]:
        if w in n:
            return "bold" if w.startswith("bold") else w
    return "regular"

def scan(extra_dirs=None):
    from fontTools.ttLib import TTFont
    search = [str(FONTS_DIR)] + SYSTEM_DIRS + (extra_dirs or [])
    found = {}
    for d in search:
        dp = Path(d)
        if not dp.exists():
            continue
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            for fp in dp.rglob(ext):
                try:
                    if fp.suffix.lower() == ".ttc":
                        f = TTFont(str(fp), fontNumber=0, lazy=True)
                    else:
                        f = TTFont(str(fp), lazy=True)
                    name = ""
                    for rec in f["name"].names:
                        if rec.nameID in (16, 1):
                            try:
                                name = rec.toUnicode()
                                if name:
                                    break
                            except Exception:
                                pass
                    family = name or fp.stem
                    key = "".join(c.lower() if c.isalnum() else "_" for c in family).strip("_")
                    # disambiguate
                    base, i = key, 2
                    while base in found and found[base]["path"] != str(fp):
                        base = f"{key}_{i}"; i += 1
                    key = base
                    if key not in found:
                        found[key] = {"path": str(fp), "family": family,
                            "language": _lang_hint(str(fp), family),
                            "weights": [_weight_hint(fp.stem + family)],
                            "source": "bundled" if str(fp).startswith(str(FONTS_DIR)) else "system"}
                except Exception:
                    continue
    # merge weights for same family
    merged: dict = {}
    for k, v in found.items():
        fam = v["family"]
        if fam not in merged:
            merged[fam] = v
        else:
            for w in v["weights"]:
                if w not in merged[fam]["weights"]:
                    merged[fam]["weights"].append(w)
    out = {"fonts": {}}
    for fam, v in merged.items():
        key = "".join(c.lower() if c.isalnum() else "_" for c in fam).strip("_")
        out["fonts"][key] = v
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    (FONTS_DIR / "registry.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    n_bn = sum(1 for v in out["fonts"].values() if "bn" in v["language"])
    print(f"Scanned {len(out['fonts'])} families ({n_bn} with Bengali) → {FONTS_DIR/'registry.json'}")
    return out

if __name__ == "__main__":
    scan()
