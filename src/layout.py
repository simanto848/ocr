"""Layout reconstruction: word boxes → lines → paragraph blocks.

The detector returns word-level boxes. Joining them with newlines produces the
one-word-per-line output and tiny crops recognize badly. Instead:
  1. merge_boxes_into_lines() — cluster word boxes into line boxes (geometry only)
  2. recognize the LINE crops (far more accurate for TrOCR)
  3. group_lines_into_blocks() — cluster lines into paragraphs by vertical gap
"""
from __future__ import annotations
import env_bootstrap  # noqa: F401  (must be first: pins all caches to external drive)


def merge_boxes_into_lines(boxes, y_tol: float = 0.5):
    """Cluster [x1,y1,x2,y2] word boxes into line boxes. Returns merged boxes
    sorted top-to-bottom; words within a line sorted left-to-right."""
    clusters: list[list] = []
    for b in sorted(boxes, key=lambda b: ((b[1] + b[3]) / 2, b[0])):
        cy, h = (b[1] + b[3]) / 2, max(1, b[3] - b[1])
        placed = False
        for cl in clusters:
            lcy = sum((x[1] + x[3]) / 2 for x in cl) / len(cl)
            lh = sum(max(1, x[3] - x[1]) for x in cl) / len(cl)
            if abs(cy - lcy) <= y_tol * max(h, lh):
                cl.append(b)
                placed = True
                break
        if not placed:
            clusters.append([b])
    lines = []
    for cl in clusters:
        cl.sort(key=lambda b: b[0])
        lines.append([min(b[0] for b in cl), min(b[1] for b in cl),
                      max(b[2] for b in cl), max(b[3] for b in cl)])
    return sorted(lines, key=lambda b: (b[1], b[0]))


def attach_texts(line_boxes, texts):
    return [{"box": b, "text": t} for b, t in zip(line_boxes, texts)]


def group_lines_into_blocks(lines, gap_mult: float = 1.5, x_tol: float = 40):
    """Cluster line dicts ({box, text}) into paragraph blocks. A new block
    starts on a large vertical gap. Returns [{box, lines:[...], text}]."""
    if not lines:
        return []
    hs = sorted(l["box"][3] - l["box"][1] for l in lines)
    med_h = hs[len(hs) // 2] or 20
    blocks, cur = [], [lines[0]]
    for prev, line in zip(lines, lines[1:]):
        gap = line["box"][1] - prev["box"][3]
        x_shift = abs(line["box"][0] - prev["box"][0])
        if gap > gap_mult * med_h or x_shift > x_tol * 3:
            blocks.append(cur)
            cur = [line]
        else:
            cur.append(line)
    blocks.append(cur)
    out = []
    for bl in blocks:
        x1 = min(l["box"][0] for l in bl)
        y1 = min(l["box"][1] for l in bl)
        x2 = max(l["box"][2] for l in bl)
        y2 = max(l["box"][3] for l in bl)
        out.append({"box": [x1, y1, x2, y2],
                    "lines": [l["text"] for l in bl],
                    "text": " ".join(t for t in (l["text"] for l in bl) if t).strip()})
    return [b for b in out if b["text"]]


def blocks_to_text(blocks):
    return "\n\n".join(b["text"] for b in blocks)
