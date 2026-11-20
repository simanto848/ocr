"""MCQ extraction and dataset builder (pure standard library).

Input is the text **already extracted** from a document by ``src/extract.py`` —
this module never runs OCR itself. It recognises multiple-choice blocks in
English, Bangla and Hindi layouts and emits one canonical record per question.

Recognised conventions
----------------------
* question numbering: ``1.``, ``1)``, ``(1)``, ``Q1.``, ``১।``, ``१.``
* option labels: ``A)`` ``(B)`` ``C.`` ``ক)`` ``ख)`` ``1)`` (inline or stacked)
* inline answer: ``Answer: B``, ``Ans - (c)``, ``উত্তর: গ``, ``उत्तर: ख``
* answer key: ``Answer Key`` / ``উত্তরমালা`` then ``1. B 2. C`` or ``1-B, 2-C``
* marked option: ``**B) ...**``, ``✔ B) ...``, ``[x] B) ...``, ``B) ... (correct)``
* explanation: ``Explanation:`` / ``ব্যাখ্যা:`` / ``व्याख्या:``
* comprehension passages: ``Passage:`` / ``উদ্দীপক`` / ``निम्नलिखित``

Exports (see ``FORMATS``)
-------------------------
``jsonl``  canonical records (review/edit)         ``rag``    one chunk per question
``sft``    chat fine-tuning (system/user/assistant) ``alpaca`` instruction tuning
``csv``    spreadsheet review                      ``md``     human readable
``card``   dataset card (provenance + caveats)

CLI
---
``python -m mcq --job outputs/web/jobs/<id>/result.json --out data/mcq_x``
``python -m mcq --text paper.txt --out data/mcq_x --name "Class 9 Biology"``
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "1.0"

# --------------------------------------------------------------------------- #
# characters / labels
# --------------------------------------------------------------------------- #
BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
HI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_BN_LABELS = {"ক": "A", "খ": "B", "গ": "C", "ঘ": "D", "ঙ": "E"}
_HI_LABELS = {"क": "A", "ख": "B", "ग": "C", "घ": "D", "ङ": "E"}
_DIGIT_LABELS = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E",
                 "১": "A", "২": "B", "৩": "C", "৪": "D", "৫": "E",
                 "१": "A", "२": "B", "३": "C", "४": "D", "५": "E"}
# One character class used by every regex below.
LC = "A-Ea-eকখগঘঙकखगघङ1-5১২৩৪৫१२३४५"


def label_of(ch: str) -> str | None:
    """Map A/a/ক/क/1/১ to a canonical letter A..E."""
    ch = (ch or "").strip()
    if not ch:
        return None
    if ch in "ABCDE":
        return ch
    if ch in "abcde":
        return ch.upper()
    if ch in _BN_LABELS:
        return _BN_LABELS[ch]
    if ch in _HI_LABELS:
        return _HI_LABELS[ch]
    return _DIGIT_LABELS.get(ch)


def ascii_digits(text: str) -> str:
    return text.translate(BN_DIGITS).translate(HI_DIGITS)


# --------------------------------------------------------------------------- #
# regexes
# --------------------------------------------------------------------------- #
_Q_RE = re.compile(
    r"^\s*(?:(?:Q|Question|প্রশ্ন|प्रश्न)\s*\.?\s*)?"
    r"\(?([0-9০-৯०-९]{1,3})\)?\s*[.)।:\-–]\s+(.+)$", re.I)

_OPT_RE = re.compile(
    rf"^\s*\(?([{LC}])\)?\s*[).।:\-–]\s*(.+)$")

_BULLET_RE = re.compile(r"^\s*[•·▪◦\-–—]\s+(.+)$")

_ANS_RE = re.compile(
    r"^\s*(?:correct\s*(?:answer|option)|answer|ans|sol(?:ution)?|"
    r"উত্তর|সঠিক\s*উত্তর|उत्तर|सही\s*उत्तर)\s*(?:is)?\s*[:\-–=.]*\s*"
    rf"(?:option\s*|বিকল্প\s*|विकल्प\s*)?\(?([{LC}])\)?(?!\w)\s*(.*)$", re.I)

_INLINE_ANS_RE = re.compile(
    r"\s*[\(\[\{]?\s*(?:answer|ans|উত্তর|उत्तर)\s*[:\-–]\s*"
    r"\(?([" + LC + r"])\)?[\)\]\}]?\s*$", re.I)

_EXP_RE = re.compile(
    r"^\s*(?:explanation|reason(?:ing)?|solution|"
    r"ব্যাখ্যা|व्याख्या)\s*[:\-–]\s*(.*)$", re.I)

_KEY_HDR_RE = re.compile(
    r"^\s*(?:answer\s*key|answers?(?:\s*key)?|key|"
    r"উত্তরমালা|উত্তর\s*পত্র|उत्तर\s*कुंजी|उत्तरमाला)\s*[:\-–]?\s*$", re.I)

_KEY_PAIR_RE = re.compile(
    rf"(\d{{1,3}})\s*[.)।:\-–]?\s*\(?([{LC}])\)?(?=\s*(?:[,;.]|\d|$))")

_PASSAGE_RE = re.compile(
    r"^\s*(?:passage|read\s+the\s+following|comprehension|"
    r"উদ্দীপক|অনুচ্ছেদ|निम्नलिखित)\b\s*[:\-–]?\s*(.*)$", re.I)

_FOOTER_RE = re.compile(
    r"^\s*(?:page|পৃষ্ঠা|पृष्ठ)\s*[0-9০-৯०-९]{1,3}"
    r"(?:\s*(?:of|/)\s*[0-9০-৯०-९]{1,3})?\s*$"
    r"|^\s*[0-9০-৯०-९]{1,3}\s*$", re.I)

_BOLD_RE = re.compile(r"^\*\*(.+?)\*\*\s*$|^__(.+?)__\s*$")
_MARK_PREFIX_RE = re.compile(r"^(?:[✔✓√☑✅★]|\[[xX]\]|\(x\))\s*")
_MARK_SUFFIX_RE = re.compile(r"\s*(?:\((?:correct|answer|সঠিক|उत्तर)\)|[✔✓√☑✅])\s*$", re.I)

_INLINE_CAND_RE = re.compile(rf"\(?([{LC}])\)?[).।:\-–]\s+")

_WS_RE = re.compile(r"\s+")

MAX_OPTION_CHARS = 400


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _clean(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").replace("\u200b", "")).strip()


def _strip_marks(text: str) -> tuple[str, bool]:
    """Remove emphasis/checkmark decoration, reporting whether any was found.

    OCR/VLM output marks the correct option in several ways: ``**bold**``,
    ``__underline__``, a leading ``✔``/``[x]``, or a trailing ``(correct)``.
    Left in place the markers pollute the option text, so both the option and
    the bullet paths run text through this.
    """
    text = (text or "").strip()
    marked = False
    m = _BOLD_RE.match(text)
    if m:
        text = (m.group(1) or m.group(2) or "").strip()
        marked = True
    if _MARK_PREFIX_RE.match(text):
        text = _MARK_PREFIX_RE.sub("", text)
        marked = True
    if _MARK_SUFFIX_RE.search(text):
        text = _MARK_SUFFIX_RE.sub("", text)
        marked = True
    return text, marked


def detect_language(text: str) -> str:
    bn = sum(1 for c in text if "\u0980" <= c <= "\u09FF")
    hi = sum(1 for c in text if "\u0900" <= c <= "\u097F")
    la = sum(1 for c in text if c.isascii() and c.isalpha())
    total = bn + hi + la
    if not total:
        return "unknown"
    if bn / total > 0.2 and la / total > 0.2:
        return "bn-en"
    if bn / total > 0.2 and hi / total > 0.2:
        return "bn-hi"
    if bn / total > 0.2:
        return "bn"
    if hi / total > 0.2:
        return "hi"
    return "en"


def split_inline_options(text: str):
    """Split ``A) one B) two C) three`` into (stem, [(label, text), ...]).

    Only splits when at least two markers form a letter sequence, which is what
    keeps prose such as "A. Smith said" from being treated as options.
    """
    cands = list(_INLINE_CAND_RE.finditer(text))
    if len(cands) < 2:
        return text, []
    accepted = []
    expected = None
    for m in cands:
        if m.start() > 0 and not text[m.start() - 1].isspace():
            continue
        lab = label_of(m.group(1))
        if not lab:
            continue
        if expected is None:
            expected = lab
        elif lab != expected:
            continue
        accepted.append((lab, m))
        expected = chr(ord(expected) + 1)
    if len(accepted) < 2:
        return text, []
    lead = text[:accepted[0][1].start()].strip(" \t,;:-")
    opts = []
    for i, (lab, m) in enumerate(accepted):
        end = accepted[i + 1][1].start() if i + 1 < len(accepted) else len(text)
        body = text[m.end():end].strip(" \t,;:-")
        if body:
            opts.append((lab, body))
    return lead, opts


def _key_pairs(line: str):
    return _KEY_PAIR_RE.findall(ascii_digits(line))


def _uid(question: str, options) -> str:
    base = _clean(question).casefold() + "|" + "|".join(
        _clean(o["text"]).casefold() for o in options)
    return "mcq_" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
@dataclass
class _Q:
    number: int | None
    text: str
    page: int | None
    options: list = field(default_factory=list)
    answer: str | None = None
    explanation: str = ""
    passage: str = ""
    raw: list = field(default_factory=list)
    out_of_order: bool = False


class _Parser:
    def __init__(self, answer_mode: str = "auto"):
        self.answer_mode = answer_mode if answer_mode in (
            "auto", "inline", "key", "none") else "auto"
        self.use_inline = self.answer_mode in ("auto", "inline")
        self.use_key = self.answer_mode in ("auto", "key")
        self.questions: list[_Q] = []
        self.key: dict[int, str] = {}
        self.warnings: list[str] = []
        self.cur: _Q | None = None
        self.mode = "idle"           # idle | question | options | explanation | key
        self.passage = ""
        self.passage_mode = False
        self.pending_bullets: list[tuple[str, bool]] = []
        self.skipped = 0

    # -- structure --------------------------------------------------------- #
    def _start_question(self, num: int, stem: str, page):
        self._flush_bullets()
        self._finish()
        stem = _clean(stem)
        answer = None
        m = _INLINE_ANS_RE.search(stem)
        if m:
            # Always strip the answer marker from the stem, even when the
            # chosen mode ignores answers — otherwise it leaks into the text.
            lab = label_of(m.group(1))
            if lab and self.use_inline:
                answer = lab
            stem = stem[:m.start()].strip()
        lead, inline = split_inline_options(stem)
        q = _Q(number=num, text=_clean(lead) or stem, page=page,
               answer=answer, passage=self.passage, raw=[])
        if inline:
            for lab, txt in inline:
                self.cur = q
                self._add_option(lab, txt)
            self.cur = q
            self.mode = "options"
        else:
            self.mode = "question"
        self.cur = q

    def _add_option(self, lab: str, text: str, marked: bool = False) -> bool:
        q = self.cur
        if q is None:
            return False
        text = _clean(text)
        if not text or len(text) > MAX_OPTION_CHARS:
            return False
        if any(o["label"] == lab for o in q.options):
            return False
        expected = "ABCDE"[len(q.options)] if len(q.options) < 5 else None
        if expected and lab != expected:
            q.out_of_order = True
        q.options.append({"label": lab, "text": text})
        if marked:
            self._set_answer(lab)
        return True

    def _set_answer(self, lab: str | None):
        if self.cur is not None and lab and self.use_inline and self.cur.answer is None:
            self.cur.answer = lab

    def _flush_bullets(self):
        bullets, self.pending_bullets = self.pending_bullets, []
        q = self.cur
        if not q or not bullets:
            return
        if len(bullets) >= 2 and not q.options:
            for text, marked in bullets[:5]:
                self._add_option("ABCDE"[len(q.options)], text, marked)
        else:
            for text, _ in bullets:
                self._append(text)

    def _append(self, text: str):
        q = self.cur
        if q is None:
            return
        text = _clean(text)
        if not text:
            return
        if self.mode == "explanation":
            q.explanation = _clean(q.explanation + " " + text)
        elif q.options:
            last = q.options[-1]
            if len(last["text"]) < MAX_OPTION_CHARS:
                last["text"] = _clean(last["text"] + " " + text)
            else:
                q.text = _clean(q.text + " " + text)
        else:
            q.text = _clean(q.text + " " + text)

    def _finish(self):
        self._flush_bullets()
        q, self.cur = self.cur, None
        if q is None:
            return
        q.text = _clean(q.text)
        if not q.text:
            self.skipped += 1
            return
        if len(q.options) < 2 and not q.answer:
            # a numbered heading / list item, not a question
            self.skipped += 1
            return
        if len(q.options) > 5:
            self.warnings.append(f"question {q.number}: {len(q.options)} options (kept first 5)")
            q.options = q.options[:5]
        self.questions.append(q)

    # -- feeding ----------------------------------------------------------- #
    def feed(self, line: str, page=None):
        s = (line or "").strip()
        if not s or _FOOTER_RE.match(s):
            return
        q = self.cur
        if q is not None:
            q.raw.append(s)

        marked = False
        m = _BOLD_RE.match(s)
        if m:
            s = (m.group(1) or m.group(2) or "").strip()
            marked = True
        if _MARK_PREFIX_RE.match(s):
            s = _MARK_PREFIX_RE.sub("", s)
            marked = True

        # answer key header
        if _KEY_HDR_RE.match(s):
            self._flush_bullets()
            self._finish()
            self.mode = "key"
            return

        # answer key rows
        pairs = _key_pairs(s)
        if pairs and (self.mode == "key" or len(pairs) >= 2):
            if self.mode == "key" or not _Q_RE.match(s):
                for num, lab in pairs:
                    mapped = label_of(lab)
                    if mapped:
                        self.key[int(num)] = mapped
                return

        # explanation
        m = _EXP_RE.match(s)
        if m and q is not None:
            self.mode = "explanation"
            q.explanation = _clean(q.explanation + " " + (m.group(1) or ""))
            return

        # inline answer: consume the line in every mode. With answer_mode
        # 'none'/'key' we ignore the label, but leaving it in the stream would
        # append "Answer: C" to the last option's text.
        m = _ANS_RE.match(s)
        if m and q is not None:
            lab = label_of(m.group(1))
            if lab and self.use_inline:
                self._set_answer(lab)
            rest = _clean(m.group(2) or "")
            if rest and not q.explanation:
                q.explanation = rest
            return

        # passage
        m = _PASSAGE_RE.match(s)
        if m:
            self._flush_bullets()
            self._finish()
            self.passage = _clean(m.group(1) or "")
            self.passage_mode = True
            self.mode = "idle"
            return

        # Numeric option lists ("1) Mars / 2) Venus") collide with question
        # numbering. A short, question-mark-free line whose number is the next
        # expected option label is an option when a question is already open.
        if q is not None and len(q.options) < 5:
            mo = _OPT_RE.match(s)
            if mo and mo.group(1) in "12345১২৩৪৫१२३४५":
                body = _clean(mo.group(2))
                expected = "ABCDE"[len(q.options)]
                if (label_of(mo.group(1)) == expected and body
                        and "?" not in body and len(body.split()) <= 12):
                    self._flush_bullets()
                    self.mode = "options"
                    b, bm = _strip_marks(body)
                    self._add_option(expected, b, marked or bm)
                    return

        # new question
        m = _Q_RE.match(s)
        if m:
            num = int(ascii_digits(m.group(1)))
            stem = m.group(2)
            if 0 < num <= 999 and len(_clean(stem)) >= 2:
                self._start_question(num, stem, page)
                return

        if q is not None:
            # option on its own line
            m = _OPT_RE.match(s)
            if m:
                lab = label_of(m.group(1))
                text = m.group(2)
                if lab and _clean(text) and len(_clean(text)) <= MAX_OPTION_CHARS:
                    self._flush_bullets()
                    self.mode = "options"
                    body, body_marked = _strip_marks(text)
                    self._add_option(lab, body, marked or body_marked)
                    return
            # bullet option (buffered: needs a run of >= 2)
            m = _BULLET_RE.match(s)
            if m and len(q.options) + len(self.pending_bullets) < 5:
                body, body_marked = _strip_marks(m.group(1))
                self.pending_bullets.append((body, marked or body_marked))
                return
            self._append(s)
            return

        # no current question: prose belongs to a passage if we are in one
        if self.passage_mode:
            self.passage = _clean(self.passage + " " + s)

    def resolve_keys(self):
        if not self.use_key or not self.key:
            return
        used, dup_numbers = set(), Counter()
        for q in self.questions:
            if q.number is not None:
                dup_numbers[q.number] += 1
        for q in self.questions:
            if q.number is None:
                continue
            if q.answer:
                # already resolved inline; its key slot is not "unused"
                used.add(q.number)
                continue
            if q.number in self.key and q.number not in used:
                q.answer = self.key[q.number]
                used.add(q.number)
        repeated = [n for n, c in dup_numbers.items() if c > 1]
        if repeated:
            self.warnings.append(
                "question numbers repeat (" + ", ".join(map(str, repeated[:5])) + ")"
                " — answer-key mapping may be ambiguous")
        missing = sorted(set(self.key) - used)
        if missing:
            self.warnings.append(
                f"answer key has {len(missing)} unused entr"
                f"{'y' if len(missing) == 1 else 'ies'} (e.g. {missing[:5]})")

    def finalize(self) -> list[dict]:
        self._flush_bullets()
        self._finish()
        self.resolve_keys()
        items, seen = [], {}
        for i, q in enumerate(self.questions):
            labels = [o["label"] for o in q.options]
            ans = None
            if q.answer:
                idx = labels.index(q.answer) if q.answer in labels else -1
                ans = {"label": q.answer,
                       "text": q.options[idx]["text"] if idx >= 0 else "",
                       "index": idx if idx >= 0 else None}
            sequential = labels == list("ABCDE"[:len(labels)])
            confidence = 0.30
            if ans and ans["index"] is not None:
                confidence += 0.25
            if len(q.options) >= 3:
                confidence += 0.15
            elif len(q.options) == 2:
                confidence += 0.08
            if sequential:
                confidence += 0.10
            if q.options and all(1 <= len(o["text"]) <= 200 for o in q.options):
                confidence += 0.08
            if len(q.text) >= 12:
                confidence += 0.07
            if q.explanation:
                confidence += 0.05
            if q.out_of_order:
                confidence -= 0.15
            texts = [o["text"].casefold() for o in q.options]
            if len(texts) != len(set(texts)):
                confidence -= 0.20
            confidence = round(max(0.05, min(0.99, confidence)), 2)
            uid = _uid(q.text, q.options)
            if uid in seen:
                seen[uid] += 1
                continue
            seen[uid] = 1
            items.append({
                "id": f"mcq_{len(items) + 1:04d}",
                "uid": uid,
                "number": q.number,
                "question": q.text,
                "options": q.options,
                "answer": ans,
                "explanation": q.explanation,
                "passage": q.passage,
                "language": detect_language(
                    " ".join([q.text, q.explanation] + [o["text"] for o in q.options])),
                "confidence": confidence,
                # A question with no resolved answer always needs a human, even
                # when the structure was clean — nothing else can fill it in.
                "needs_review": confidence < 0.7 or ans is None,
                "include": True,
                "source": {"page": q.page},
                "raw": "\n".join(q.raw)[:2000],
            })
        removed = sum(c - 1 for c in seen.values() if c > 1)
        if removed:
            self.warnings.append(f"{removed} duplicate question(s) removed")
        self.duplicates_removed = removed
        return items


# --------------------------------------------------------------------------- #
# public parse API
# --------------------------------------------------------------------------- #
def parse_pages(pages, source: dict | None = None,
                answer_mode: str = "auto") -> dict:
    """Parse a list of ``{page, text}`` dicts (as produced by ``extract.py``)."""
    parser = _Parser(answer_mode)
    for pg in pages or []:
        text = pg.get("text") or ""
        for line in text.splitlines():
            parser.feed(line, pg.get("page"))
    items = parser.finalize()
    for it in items:
        it["source"] = {**(source or {}), **(it.get("source") or {})}
    return {"items": items, "warnings": parser.warnings,
            "skipped": parser.skipped, "parser": VERSION}


def parse_text(text: str, source: dict | None = None,
               answer_mode: str = "auto") -> dict:
    return parse_pages([{"page": 1, "text": text}], source, answer_mode)


# --------------------------------------------------------------------------- #
# dataset assembly / exports
# --------------------------------------------------------------------------- #
def normalize_items(items, dedupe: bool = True) -> tuple[list[dict], int]:
    """Deduplicate by uid and assign sequential human ids.

    ``dedupe=False`` keeps every element, which is what the review editor needs:
    an edit that happens to make two records identical must not silently delete
    the user's work.
    """
    out, seen, dup = [], set(), 0
    for it in items:
        uid = it.get("uid") or _uid(it.get("question", ""), it.get("options") or [])
        if dedupe and uid in seen:
            dup += 1
            continue
        seen.add(uid)
        it = dict(it)
        it["uid"] = uid
        it["id"] = f"mcq_{len(out) + 1:04d}"
        it.setdefault("include", True)
        out.append(it)
    return out, dup


def set_item_answer(item: dict, label: str | None):
    """Set/clear an answer consistently (used by the review UI)."""
    label = label_of(label) if label else None
    if label and label not in [o["label"] for o in item.get("options") or []]:
        label = None
    if not label:
        item["answer"] = None
        return item
    idx = next(i for i, o in enumerate(item["options"]) if o["label"] == label)
    item["answer"] = {"label": label, "text": item["options"][idx]["text"], "index": idx}
    item["needs_review"] = False
    item["confidence"] = max(float(item.get("confidence") or 0), 0.95)
    return item


def _norm_tokens(text: str):
    return {t for t in re.findall(r"\w+", ascii_digits(text or "").casefold())
            if len(t) > 1}


def attach_boxes(items, pages) -> list:
    """Link extracted questions to OCR line boxes for source highlighting.

    Adds ``bbox``, ``line`` and ``box_text`` to each item's ``source`` object
    when the page has OCR boxes. Uses token-overlap matching, so it works when
    OCR line breaks differ from the parser's question text.
    """
    for it in items or []:
        src = it.get("source") or {}
        try:
            pnum = int(src.get("page"))
        except (TypeError, ValueError):
            continue
        pg = next((p for p in pages or [] if p.get("page") == pnum), None)
        if not pg:
            continue
        boxes = pg.get("boxes") or []
        if not boxes:
            continue
        tokens = _norm_tokens(it.get("question", ""))
        if not tokens:
            continue
        best_i, best_score = -1, 0.0
        for i, b in enumerate(boxes):
            bt = _norm_tokens(b.get("text", ""))
            if not bt:
                continue
            score = len(tokens & bt) / max(1, len(tokens | bt))
            if score > best_score:
                best_i, best_score = i, score
        if best_i >= 0 and best_score >= 0.18:
            b = boxes[best_i]
            src["bbox"] = b.get("box")
            src["line"] = best_i
            src["box_text"] = b.get("text", "")
            if pg.get("image_size"):
                src["image_size"] = pg["image_size"]
        it["source"] = src
    return items


def dataset_stats(items) -> dict:
    inc = [i for i in items if i.get("include", True)]
    with_ans = [i for i in inc if (i.get("answer") or {}).get("index") is not None]
    return {
        "total": len(items),
        "included": len(inc),
        "with_answer": len(with_ans),
        "missing_answer": len(inc) - len(with_ans),
        "needs_review": sum(1 for i in inc if i.get("needs_review")),
        "languages": dict(Counter(i.get("language", "?") for i in inc)),
        "sources": dict(Counter(
            (i.get("source") or {}).get("filename", "?") for i in inc)),
        "avg_confidence": round(
            sum(float(i.get("confidence") or 0) for i in inc) / max(1, len(inc)), 2),
    }


def render_block(item: dict, with_answer: bool = True) -> str:
    lines = []
    if item.get("passage"):
        lines += [item["passage"], ""]
    lines.append("Q: " + (item.get("question") or ""))
    for o in item.get("options") or []:
        lines.append(f"{o['label']}) {o['text']}")
    ans = item.get("answer") or {}
    if with_answer and ans.get("label"):
        lines.append(f"Answer: {ans['label']}) {ans.get('text', '')}".rstrip(" )"))
    if item.get("explanation"):
        lines.append("Explanation: " + item["explanation"])
    return "\n".join(lines).strip()


def _jsonl(rows) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _exportable(items):
    return [i for i in items if i.get("include", True)]


def export_jsonl(items) -> str:
    return _jsonl(items)


def export_rag(items) -> str:
    rows = []
    for it in _exportable(items):
        ans = it.get("answer") or {}
        rows.append({
            "id": it["uid"],
            "text": render_block(it, with_answer=True),
            "metadata": {
                "question": it.get("question"),
                "answer_label": ans.get("label"),
                "answer_text": ans.get("text"),
                "explanation": it.get("explanation") or "",
                "language": it.get("language"),
                "source_file": (it.get("source") or {}).get("filename"),
                "source_page": (it.get("source") or {}).get("page"),
                "confidence": it.get("confidence"),
            },
        })
    return _jsonl(rows)


SFT_SYSTEM = ("You are an exam assistant. Choose the correct option for the "
              "multiple-choice question and explain briefly.")


def _sft_user(it) -> str:
    parts = []
    if it.get("passage"):
        parts += [it["passage"], ""]
    parts.append("Question: " + (it.get("question") or ""))
    parts += [f"{o['label']}. {o['text']}" for o in it.get("options") or []]
    return "\n".join(parts)


def _sft_assistant(it) -> str:
    ans = it.get("answer") or {}
    text = f"{ans.get('label')}. {ans.get('text', '')}".strip()
    if it.get("explanation"):
        text += "\n\nExplanation: " + it["explanation"]
    return text


def export_sft(items) -> str:
    rows = []
    for it in _exportable(items):
        if (it.get("answer") or {}).get("index") is None:
            continue
        rows.append({"messages": [
            {"role": "system", "content": SFT_SYSTEM},
            {"role": "user", "content": _sft_user(it)},
            {"role": "assistant", "content": _sft_assistant(it)},
        ], "metadata": {"uid": it["uid"], "language": it.get("language"),
                        "source_file": (it.get("source") or {}).get("filename")}})
    return _jsonl(rows)


def export_alpaca(items) -> str:
    rows = []
    for it in _exportable(items):
        if (it.get("answer") or {}).get("index") is None:
            continue
        instruction = (it["passage"] + "\n\n" if it.get("passage") else "") + it["question"]
        rows.append({
            "instruction": instruction,
            "input": "\n".join(f"{o['label']}) {o['text']}" for o in it.get("options") or []),
            "output": _sft_assistant(it),
            "metadata": {"uid": it["uid"], "language": it.get("language")},
        })
    return _jsonl(rows)


def export_csv(items) -> str:
    buf = io.StringIO()
    cols = ["id", "question", "option_a", "option_b", "option_c", "option_d",
            "option_e", "answer_label", "answer_text", "explanation", "passage",
            "language", "confidence", "needs_review", "source_file", "page"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for it in _exportable(items):
        opts = {f"option_{o['label'].lower()}": o["text"] for o in it.get("options") or []}
        ans = it.get("answer") or {}
        w.writerow({
            "id": it["id"], "question": it.get("question"), **opts,
            "answer_label": ans.get("label") or "", "answer_text": ans.get("text") or "",
            "explanation": it.get("explanation") or "", "passage": it.get("passage") or "",
            "language": it.get("language"), "confidence": it.get("confidence"),
            "needs_review": "yes" if it.get("needs_review") else "no",
            "source_file": (it.get("source") or {}).get("filename") or "",
            "page": (it.get("source") or {}).get("page") or "",
        })
    return buf.getvalue()


def export_markdown(items, name="MCQ dataset") -> str:
    st = dataset_stats(items)
    out = [f"# {name}", "",
           f"{st['included']} questions · {st['with_answer']} with answers · "
           f"{st['needs_review']} need review · avg confidence {st['avg_confidence']}", ""]
    by_file: dict[str, list] = {}
    for it in _exportable(items):
        by_file.setdefault((it.get("source") or {}).get("filename") or "document", []).append(it)
    for filename, group in by_file.items():
        out += [f"## {filename}", ""]
        for it in group:
            out.append(f"### {it['id']}. {it['question']}")
            if it.get("passage"):
                out += ["", f"> {it['passage']}"]
            out.append("")
            ans = it.get("answer") or {}
            for o in it.get("options") or []:
                mark = " ✓" if o["label"] == ans.get("label") else ""
                out.append(f"- **{o['label']}.** {o['text']}{mark}")
            if ans.get("label"):
                out += ["", f"**Answer:** {ans['label']}"]
            if it.get("explanation"):
                out += ["", f"_{it['explanation']}_"]
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def export_card(items, name="MCQ dataset", sources=None) -> str:
    st = dataset_stats(items)
    return f"""# Dataset card — {name}

Generated by `src/mcq.py` v{VERSION}.

## Contents
- **{st['total']}** questions extracted, **{st['included']}** included in exports
- **{st['with_answer']}** have a resolved answer, **{st['missing_answer']}** do not
- **{st['needs_review']}** flagged for human review (low confidence)
- Languages: {", ".join(f"{k} ({v})" for k, v in st['languages'].items()) or "unknown"}
- Average confidence: {st['avg_confidence']}

## Files
| file | use |
|---|---|
| `mcq.jsonl` | canonical records (all questions, editable) |
| `rag.jsonl` | one self-contained chunk per question (RAG) |
| `sft_chat.jsonl` | chat fine-tuning: system / user / assistant |
| `sft_alpaca.jsonl` | instruction / input / output fine-tuning |
| `mcq.csv` | spreadsheet review |
| `mcq.md` | human-readable review |
| `splits/train.jsonl`, `splits/val.jsonl`, `splits/test.jsonl` | 90/5/5 split of the SFT set |

## Provenance
{chr(10).join("- " + str(s) for s in (sources or ["uploaded documents"]))}

## Intended use
Retrieval-augmented generation (ground the model in the extracted Q&A) or
supervised fine-tuning of an answer/exam assistant.

## Caveats
- Text comes from OCR; recognition errors propagate into the dataset.
- Questions flagged `needs_review` or missing an answer were **not** verified.
- Only use documents you have the right to process. Review licensing before
  redistributing this dataset or a model trained on it.
"""


FORMATS = {
    "jsonl": ("mcq.jsonl", export_jsonl),
    "rag": ("rag.jsonl", export_rag),
    "sft": ("sft_chat.jsonl", export_sft),
    "alpaca": ("sft_alpaca.jsonl", export_alpaca),
    "csv": ("mcq.csv", export_csv),
    "md": ("mcq.md", export_markdown),
    "card": ("dataset_card.md", export_card),
}


def _split_of(uid: str) -> str:
    n = int(hashlib.sha1(uid.encode()).hexdigest()[:8], 16) % 20
    return "train" if n < 18 else "val" if n == 18 else "test"


def write_dataset(root, items, name=None, sources=None, warnings=None,
                  dedupe: bool = True) -> dict:
    """Write all artifacts under ``root`` and return {manifest, items}."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    items, dup = normalize_items(items, dedupe=dedupe)
    stats = dataset_stats(items)
    manifest = {
        "id": root.name,
        "name": name or "MCQ dataset",
        "version": VERSION,
        "created": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "sources": sources or [],
        "stats": stats,
        "duplicates_removed": dup,
        "warnings": list(warnings or []),
        "files": {},
    }
    (root / "items.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    for fmt, (filename, fn) in FORMATS.items():
        body = fn(items) if fmt not in ("md", "card") else fn(items, name=manifest["name"])
        enc = "utf-8-sig" if fmt == "csv" else "utf-8"
        (root / filename).write_text(body, encoding=enc)
        manifest["files"][fmt] = filename

    # deterministic 90/5/5 split of answered SFT records
    answered = [i for i in items if i.get("include", True)
                and (i.get("answer") or {}).get("index") is not None]
    splits = {"train": [], "val": [], "test": []}
    for it in answered:
        splits[_split_of(it["uid"])].append(it)
    (root / "splits").mkdir(exist_ok=True)
    for split, group in splits.items():
        (root / "splits" / f"{split}.jsonl").write_text(
            export_sft(group), encoding="utf-8")
    manifest["files"]["splits"] = "splits/{train,val,test}.jsonl"
    manifest["splits"] = {k: len(v) for k, v in splits.items()}

    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"manifest": manifest, "items": items}


def load_dataset(root) -> dict:
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    items = json.loads((root / "items.json").read_text(encoding="utf-8"))
    return {"manifest": manifest, "items": items}


def export_zip_bytes(bundle: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(Path(bundle["_root"]).rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(bundle["_root"]))
    return buf.getvalue()


def download_bytes(bundle: dict, fmt: str) -> tuple[bytes, str, str]:
    """Return (body, filename, content_type) for one export format or a zip."""
    root = Path(bundle["_root"])
    if fmt == "zip":
        return (export_zip_bytes(bundle), f"{root.name}.zip", "application/zip")
    if fmt not in FORMATS:
        raise KeyError(fmt)
    filename, fn = FORMATS[fmt]
    body = fn(bundle["items"]) if fmt not in ("md", "card") else fn(
        bundle["items"], name=bundle["manifest"]["name"])
    ctype = {"csv": "text/csv; charset=utf-8",
             "jsonl": "application/x-ndjson; charset=utf-8",
             "rag": "application/x-ndjson; charset=utf-8",
             "sft": "application/x-ndjson; charset=utf-8",
             "alpaca": "application/x-ndjson; charset=utf-8",
             "md": "text/markdown; charset=utf-8",
             "card": "text/markdown; charset=utf-8"}.get(fmt, "text/plain")
    data = body.encode("utf-8-sig" if fmt == "csv" else "utf-8")
    return data, filename, ctype


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main(argv=None):
    ap = argparse.ArgumentParser(description="Extract MCQs from already-extracted text")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--job", help="path to outputs/web/jobs/<id>/result.json")
    src.add_argument("--text", help="plain-text file to parse")
    src.add_argument("--dataset", help="existing dataset dir to re-export")
    ap.add_argument("--out", default="data/mcq_dataset")
    ap.add_argument("--name", default=None)
    ap.add_argument("--answer-mode", default="auto",
                    choices=["auto", "inline", "key", "none"])
    a = ap.parse_args(argv)

    if a.dataset:
        bundle = load_dataset(a.dataset)
        bundle["_root"] = a.dataset
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for fmt in list(FORMATS) + ["zip"]:
            data, fname, _ = download_bytes(bundle, fmt)
            (out / fname).write_bytes(data)
        print(f"re-exported {len(bundle['items'])} items → {out}")
        return 0

    warnings = []
    if a.job:
        job = json.loads(Path(a.job).read_text(encoding="utf-8"))
        source = {"job_id": job.get("job_id"), "filename": job.get("filename"),
                  "engine": job.get("engine")}
        parsed = parse_pages(job.get("pages") or [], source, a.answer_mode)
        sources = [f"{job.get('filename')} ({job.get('job_id')})"]
        name = a.name or (Path(job.get("filename", "mcq")).stem + " — MCQs")
    else:
        text = Path(a.text).read_text(encoding="utf-8", errors="ignore")
        source = {"filename": Path(a.text).name}
        parsed = parse_text(text, source, a.answer_mode)
        sources = [str(a.text)]
        name = a.name or (Path(a.text).stem + " — MCQs")
    warnings += parsed["warnings"]

    if not parsed["items"]:
        print("No MCQs found. Check the answer-mode or the extracted text layout.",
              file=sys.stderr)
        return 2
    bundle = write_dataset(a.out, parsed["items"], name=name,
                           sources=sources, warnings=warnings)
    st = bundle["manifest"]["stats"]
    print(f"{st['included']} questions ({st['with_answer']} answered, "
          f"{st['needs_review']} need review) → {a.out}")
    for w in warnings:
        print("warn:", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
