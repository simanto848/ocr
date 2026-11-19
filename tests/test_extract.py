import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from extract import LANG_MAP, _lang_arg, _parse_tsv, extract_file  # noqa: E402


def test_lang_arg_mapping():
    assert _lang_arg("auto") == "eng+ben+hin"
    assert _lang_arg("bn") == "ben"
    assert _lang_arg("hindi") == "hin"
    assert _lang_arg("something-else") == "eng+ben+hin"
    assert {"eng", "ben", "hin"}.issubset(set(LANG_MAP.values()))


def test_parse_tsv_groups_words_into_lines():
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [
        f"{header}",
        "5\t1\t1\t1\t1\t1\t10\t10\t30\t20\t95.0\tHello",
        "5\t1\t1\t1\t1\t2\t45\t10\t30\t20\t94.0\tworld",
        "5\t1\t1\t1\t2\t1\t10\t40\t50\t20\t90.0\tSecond",
    ]
    lines = _parse_tsv("\n".join(rows))
    assert len(lines) == 2
    assert lines[0]["text"] == "Hello world"
    assert lines[0]["box"] == [10, 10, 75, 30]
    assert lines[1]["text"] == "Second"


def test_extract_docx_multilingual(tmp_path):
    import docx
    p = tmp_path / "sample.docx"
    d = docx.Document()
    d.add_paragraph("Hello World — English text")
    d.add_paragraph("নমস্কার, এটি বাংলা পাঠ্য।")
    d.add_paragraph("नमस्ते, यह हिंदी पाठ है।")
    d.save(p)

    result = extract_file(p, lang="auto", out_dir=tmp_path / "out")
    text = "\n".join(pg["text"] for pg in result["pages"])
    assert "Hello World" in text
    assert "বাংলা" in text
    assert "हिंदी" in text
    assert result["ocr_langs"] == ["eng", "ben", "hin"]
    # Each page carries an internal render filename used by the web UI.
    for pg in result["pages"]:
        assert (tmp_path / "out" / pg["render"]).is_file()
