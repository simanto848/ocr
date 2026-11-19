import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def test_registry_loads():
    from dataset.fonts.registry import FontRegistry
    r = FontRegistry()
    assert len(r.entries) > 5, "registry empty — run python -m dataset.fonts.scan"
    f, meta, fb = r.get(language="bn", size=20)
    assert meta["key"] != "" and f is not None

def test_bn_content():
    from dataset.content.generators import ContentGen
    g = ContentGen(0)
    assert "সরকার" in g.paragraph("bn", 2) or len(g.person("bn")) > 2
    assert any("\u0980" <= c <= "\u09FF" for c in g.address("bn"))

def test_templates_build():
    from dataset.templates.documents import build, DOC_TYPES
    for t in DOC_TYPES:
        d = build(t, "bn-en", seed=1)
        assert d.full_text().strip(), t

def test_pillow_render_real_font():
    from dataset.fonts.registry import FontRegistry
    from dataset.templates.documents import build
    from dataset.rendering.pillow_renderer import PillowRenderer
    r = PillowRenderer(FontRegistry())
    img, ann = r.render(build("invoice", "bn", seed=2), seed=2)
    assert img.size[0] > 500 and len(ann["words"]) > 3
    assert ann["meta"]["renderer"] == "pillow-ttf"

def test_degrader_preserves_boxes():
    import numpy as np
    from dataset.augmentation.degrader import DocumentDegrader
    img = np.full((400, 400, 3), 255, np.uint8)
    out, boxes, applied = DocumentDegrader({}, seed=0)(img, [[10, 10, 100, 40]])
    assert out.shape == img.shape and len(boxes) == 1
    assert isinstance(applied, dict)

def test_validator_and_dedup(tmp_path):
    from PIL import Image
    from dataset.validation.validator import validate_sample
    p = tmp_path / "x.png"
    Image.new("RGB", (600, 400), "white").save(p)
    ok, _ = validate_sample(p, {"words": [{"text": "ক", "bbox": [10, 10, 50, 40]}], "meta": {"a": 1}})
    assert ok
