# Annotations

From structured `Document` (never OCR): `annotations/<id>.json` =
`{id, text, words[{text,bbox,level}], lines[...], document{schema}}`.
Levels: word/line (+block via elements). Tables/KV preserved in `document.pages[].elements`.
Degradation bboxes are transformed, never reused raw.
