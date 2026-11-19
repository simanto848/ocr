"""Document schema: Document → Pages → Elements. Single source of truth for GT."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import uuid

ELEMENT_TYPES = {"text", "heading", "paragraph", "table", "field", "checkbox",
                 "header", "footer", "logo", "signature", "stamp", "watermark",
                 "line", "rectangle", "page_number", "image"}

@dataclass
class Element:
    type: str
    text: str = ""
    font_family: str = ""
    font_size: int = 20
    font_weight: str = "regular"
    alignment: str = "left"
    bbox: list = field(default_factory=list)  # filled by renderer [x1,y1,x2,y2]
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        assert self.type in ELEMENT_TYPES, f"bad element type {self.type}"

@dataclass
class Page:
    page_number: int
    elements: list = field(default_factory=list)
    size: str = "A4"
    dpi: int = 300

@dataclass
class Document:
    document_id: str
    language: str  # bn | en | bn-en
    document_type: str
    pages: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self):
        return {"document_id": self.document_id, "language": self.language,
                "document_type": self.document_type,
                "pages": [{"page_number": p.page_number, "size": p.size, "dpi": p.dpi,
                           "elements": [asdict(e) for e in p.elements]} for p in self.pages],
                "meta": self.meta}

    def full_text(self):
        return "\n".join(e.text for p in self.pages for e in p.elements if e.text)

def new_doc(doc_type, language, seed=0):
    return Document(document_id=f"doc_{seed:06d}", language=language,
                    document_type=doc_type, pages=[Page(page_number=1)])
