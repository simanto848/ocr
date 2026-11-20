"""Tests for the MCQ parser and dataset builder (no OCR, no network)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mcq  # noqa: E402

ENGLISH = """\
1. What is the capital of France?
A) Berlin
B) Madrid
C) Paris
D) Rome
Answer: C

2. Which gas do plants absorb?
A) Oxygen
B) Carbon dioxide
C) Nitrogen
D) Hydrogen
Ans: B
"""

INLINE = """\
1) Pick the primary colour (a) red (b) green (c) blue
Ans: (a)

2) Which is a mammal? (A) Snake (B) Frog (C) Dog (D) Fish
Answer: (C)
"""

BANGLA = """\
৩। বাংলাদেশের রাজধানী কোনটি?
ক) ঢাকা
খ) চট্টগ্রাম
গ) খুলনা
ঘ) রাজশাহী
উত্তর: ক

৪। 'সবুজ' শব্দের অর্থ কী?
ক) নীল
খ) সবুজ
গ) লাল
ঘ) হলুদ
"""

HINDI = """\
1. भारत की राजधानी क्या है?
क) मुंबई
ख) दिल्ली
ग) कोलकाता
घ) चेन्नई
उत्तर: ख
"""

KEY = """\
1. First question?
A) one
B) two
C) three

2. Second question?
A) alpha
B) beta
C) gamma

Answer Key
1. B    2. C
"""

MARKED = """\
1. Which one is a greenhouse gas?
• Oxygen
• Nitrogen
• **Carbon dioxide**
• Argon

2. Choose the true statement.
✔ A) It is continuous.
B) It stops.
C) It is rare.
D) It is optional.

3. Final one?
__B) underlined answer__
A) wrong
C) also wrong
"""

PASSAGE = """\
Passage: Read this and answer the questions.
Water moves in a cycle.

1. What moves?
A) Air
B) Water
C) Sand
D) Rock

2. What shape is the movement?
A) A line
B) A square
C) A cycle
D) A triangle
"""


def test_english_stacked_with_inline_answers():
    r = mcq.parse_text(ENGLISH)
    assert len(r["items"]) == 2
    first, second = r["items"]
    assert [o["label"] for o in first["options"]] == ["A", "B", "C", "D"]
    assert first["options"][2]["text"] == "Paris"
    assert first["answer"]["label"] == "C"
    assert first["answer"]["text"] == "Paris"
    assert first["answer"]["index"] == 2
    assert second["answer"]["label"] == "B"
    assert first["language"] == "en"


def test_inline_options_single_line():
    r = mcq.parse_text(INLINE)
    assert len(r["items"]) == 2
    assert r["items"][0]["options"][0]["text"] == "red"
    assert r["items"][0]["answer"]["label"] == "A"
    assert r["items"][1]["options"][2]["text"] == "Dog"
    assert r["items"][1]["answer"]["label"] == "C"


def test_bangla_labels_and_digits():
    r = mcq.parse_text(BANGLA)
    assert len(r["items"]) == 2
    q1, q2 = r["items"]
    assert q1["options"][0]["text"] == "ঢাকা"
    assert q1["answer"]["label"] == "A"
    assert q1["language"].startswith("bn")
    assert q2["number"] == 4
    assert q2["answer"] is None
    assert q2["needs_review"] is True


def test_hindi_labels():
    r = mcq.parse_text(HINDI)
    assert len(r["items"]) == 1
    assert r["items"][0]["options"][1]["text"] == "दिल्ली"
    assert r["items"][0]["answer"]["label"] == "B"
    assert r["items"][0]["language"].startswith("hi")


def test_answer_key_block():
    r = mcq.parse_text(KEY)
    assert len(r["items"]) == 2
    assert r["items"][0]["answer"]["label"] == "B"
    assert r["items"][1]["answer"]["label"] == "C"
    assert not any("unused" in w for w in r["warnings"])


def test_marked_options_bold_bullet_underline():
    r = mcq.parse_text(MARKED)
    assert len(r["items"]) == 3
    gh = r["items"][0]
    # bullet list becomes options, bold option is the answer and marker stripped
    assert [o["text"] for o in gh["options"]] == [
        "Oxygen", "Nitrogen", "Carbon dioxide", "Argon"]
    assert gh["answer"]["label"] == "C"

    cont = r["items"][1]
    assert cont["answer"]["label"] == "A"
    assert cont["options"][0]["text"] == "It is continuous."

    underlined = r["items"][2]
    assert underlined["answer"]["label"] == "B"
    assert sorted(o["label"] for o in underlined["options"]) == ["A", "B", "C"]


def test_comprehension_passage_is_attached():
    r = mcq.parse_text(PASSAGE)
    assert len(r["items"]) == 2
    for it in r["items"]:
        assert "Water moves in a cycle" in it["passage"]


def test_answer_mode_none_ignores_inline_answer():
    r = mcq.parse_text(ENGLISH, answer_mode="none")
    assert all(it["answer"] is None for it in r["items"])
    assert all(it["needs_review"] for it in r["items"])


def test_deduplicates_repeated_questions():
    text = ENGLISH + "\n" + ENGLISH
    r = mcq.parse_text(text)
    assert len(r["items"]) == 2
    assert any("duplicate" in w for w in r["warnings"])


def test_non_question_numbered_list_is_skipped():
    r = mcq.parse_text("1. Introduction\nThis section explains things.\n")
    assert r["items"] == []


def test_empty_input_is_empty_not_error():
    r = mcq.parse_text("")
    assert r["items"] == []
    assert r["warnings"] == []


def test_set_item_answer_updates_confidence():
    r = mcq.parse_text(BANGLA)
    q2 = r["items"][1]
    assert q2["answer"] is None
    mcq.set_item_answer(q2, "খ")
    assert q2["answer"]["label"] == "B"
    assert q2["answer"]["text"] == "সবুজ"
    assert q2["needs_review"] is False
    assert q2["confidence"] >= 0.95
    # invalid label clears rather than crashing
    mcq.set_item_answer(q2, "Z")
    assert q2["answer"] is None


def test_dataset_stats_counts():
    r = mcq.parse_text(ENGLISH + "\n" + BANGLA)
    st = mcq.dataset_stats(r["items"])
    assert st["total"] == 4
    assert st["with_answer"] == 3
    assert st["missing_answer"] == 1
    assert "en" in st["languages"] and "bn" in st["languages"]


def test_write_dataset_produces_all_artifacts(tmp_path):
    r = mcq.parse_text(ENGLISH)
    out = tmp_path / "ds"
    bundle = mcq.write_dataset(out, r["items"], name="Test set",
                               sources=["unit test"])
    expected = {
        "items.json", "mcq.jsonl", "rag.jsonl", "sft_chat.jsonl",
        "sft_alpaca.jsonl", "mcq.csv", "mcq.md", "dataset_card.md",
        "manifest.json",
    }
    assert expected.issubset({p.name for p in out.iterdir()})
    assert (out / "splits" / "train.jsonl").is_file()

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "Test set"
    assert manifest["stats"]["included"] == 2
    assert sum(manifest["splits"].values()) == 2

    rag = [json.loads(line) for line in
           (out / "rag.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rag[0]["text"].startswith("Q: What is the capital")
    assert rag[0]["metadata"]["answer_label"] == "C"

    sft = [json.loads(line) for line in
           (out / "sft_chat.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sft[0]["messages"][0]["role"] == "system"
    assert sft[0]["messages"][2]["content"].startswith("C. Paris")

    loaded = mcq.load_dataset(out)
    assert loaded["manifest"]["id"] == "ds"
    assert len(loaded["items"]) == 2


def test_include_false_is_excluded_from_exports(tmp_path):
    r = mcq.parse_text(ENGLISH)
    r["items"][1]["include"] = False
    out = tmp_path / "ds"
    mcq.write_dataset(out, r["items"])
    rag = (out / "rag.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rag) == 1
    # but the canonical store keeps both for review
    items = json.loads((out / "items.json").read_text(encoding="utf-8"))
    assert len(items) == 2


@pytest.mark.parametrize("fmt", ["jsonl", "rag", "sft", "alpaca", "csv", "md",
                                 "card", "zip"])
def test_download_bytes_each_format(tmp_path, fmt):
    r = mcq.parse_text(ENGLISH)
    out = tmp_path / "ds"
    bundle = mcq.write_dataset(out, r["items"], name="X")
    bundle["_root"] = out
    data, filename, ctype = mcq.download_bytes(bundle, fmt)
    assert data
    assert filename
    assert ctype


def test_export_sft_skips_unanswered():
    data = mcq.parse_text(ENGLISH + "\n" + BANGLA)
    body = mcq.export_sft(data["items"])
    rows = [json.loads(l) for l in body.splitlines()]
    assert len(rows) == 3  # the Bangla question has no answer
    assert all("messages" in row for row in rows)


def test_answer_mode_none_strips_answer_line_from_options():
    """Regression: 'Answer: C' must not be appended to the last option text."""
    r = mcq.parse_text(ENGLISH, answer_mode="none")
    assert all(it["answer"] is None for it in r["items"])
    assert r["items"][0]["options"][-1]["text"] == "Rome"
    assert "Answer" not in r["items"][0]["options"][-1]["text"]


def test_answer_mode_key_ignores_but_consumes_inline_answers():
    r = mcq.parse_text(ENGLISH, answer_mode="key")
    assert all(it["answer"] is None for it in r["items"])
    assert r["items"][0]["options"][-1]["text"] == "Rome"


def test_inline_answer_at_end_of_stem_is_not_part_of_question():
    text = "1) What is 2 + 2? Answer: B\nA) 3\nB) 4\nC) 5\n"
    r = mcq.parse_text(text)
    assert r["items"][0]["question"] == "What is 2 + 2?"
    assert r["items"][0]["answer"]["label"] == "B"


def test_numbered_options_are_not_read_as_new_questions():
    text = """\
1. Which one is a planet?
1) Mars
2) Venus
3) Jupiter
4) Pluto
Ans: 1

2. Which one is a gas?
1) Oxygen
2) Iron
3) Gold
4) Water
Answer: 1
"""
    r = mcq.parse_text(text)
    assert len(r["items"]) == 2
    assert [o["label"] for o in r["items"][0]["options"]] == ["A", "B", "C", "D"]
    assert r["items"][0]["options"][0]["text"] == "Mars"
    assert r["items"][0]["answer"]["label"] == "A"
    assert r["items"][1]["question"] == "Which one is a gas?"


def test_question_after_short_option_is_still_a_new_question():
    text = """\
1. Pick one?
1) Alpha
2) Beta
2. Another question with a question mark?
1) Gamma
2) Delta
"""
    r = mcq.parse_text(text)
    assert len(r["items"]) == 2
    assert r["items"][1]["question"] == "Another question with a question mark?"


def test_attach_boxes_links_questions_to_source_lines():
    pages = [{
        "page": 1,
        "text": "1. What is the capital of France?\nA) Berlin\nB) Paris",
        "boxes": [
            {"box": [10, 20, 400, 45], "text": "1. What is the capital of France?"},
            {"box": [10, 55, 200, 75], "text": "A) Berlin"},
            {"box": [10, 85, 200, 105], "text": "B) Paris"},
        ],
        "image_size": [800, 1100],
        "source": "ocr",
    }]
    items = mcq.parse_pages(pages)["items"]
    assert len(items) == 1
    mcq.attach_boxes(items, pages)
    src = items[0]["source"]
    assert src["bbox"] == [10, 20, 400, 45]
    assert src["line"] == 0
    assert src["image_size"] == [800, 1100]
    assert "capital" in src["box_text"]


def test_attach_boxes_noop_without_boxes():
    pages = [{"page": 1, "text": "1. Question?\nA) one\nB) two", "boxes": []}]
    items = mcq.parse_pages(pages)["items"]
    mcq.attach_boxes(items, pages)
    assert "bbox" not in items[0]["source"]


def test_rag_and_sft_exports_include_source_geometry():
    r = mcq.parse_text(ENGLISH)
    r["items"][0]["source"].update({
        "bbox": [10, 20, 400, 45], "line": 0, "filename": "quiz.pdf"})
    rag = [json.loads(x) for x in mcq.export_rag(r["items"]).splitlines()]
    assert rag[0]["metadata"]["source_bbox"] == [10, 20, 400, 45]
    assert rag[0]["metadata"]["source_line"] == 0
    sft = [json.loads(x) for x in mcq.export_sft(r["items"]).splitlines()]
    assert sft[0]["metadata"]["source_bbox"] == [10, 20, 400, 45]
