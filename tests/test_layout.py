import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from layout import merge_boxes_into_lines, group_lines_into_blocks, blocks_to_text


def test_merge_two_lines():
    boxes = [[10, 10, 50, 30], [55, 11, 95, 30],   # line 1 (two words)
             [10, 40, 60, 60], [65, 41, 120, 60]]  # line 2
    lines = merge_boxes_into_lines(boxes)
    assert len(lines) == 2, lines
    assert lines[0][0] == 10 and lines[0][2] == 95  # x-span covers both words
    assert lines[0][1] < lines[1][1]  # top-to-bottom


def test_single_word_lines_kept():
    boxes = [[300, 10, 380, 30], [10, 100, 90, 120]]
    lines = merge_boxes_into_lines(boxes)
    assert len(lines) == 2


def test_blocks_split_on_gap():
    lines = [{"box": [10, 10, 200, 30], "text": "Title here"},
             {"box": [10, 100, 200, 120], "text": "Body starts"}]
    blocks = group_lines_into_blocks(lines)
    assert len(blocks) == 2
    assert blocks[0]["text"] == "Title here"


def test_blocks_join_close_lines():
    lines = [{"box": [10, 10, 200, 30], "text": "Hello"},
             {"box": [10, 34, 200, 54], "text": "world"}]
    blocks = group_lines_into_blocks(lines)
    assert len(blocks) == 1
    assert blocks[0]["text"] == "Hello world"
    assert blocks_to_text(blocks) == "Hello world"
