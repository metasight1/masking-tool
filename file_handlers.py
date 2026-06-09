# -*- coding: utf-8 -*-
"""
file_handlers.py
파일 형식별로 '사본'을 만들고 그 사본에만 마스킹을 적용한다.
원본 파일은 절대 수정하지 않는다.

마스킹 대상:
  - 정규식 PII (주민번호/전화/이메일/카드/계좌/여권)  -> masking_engine
  - NER 이름/주소 (한/영/일)                          -> ner_engine (Stanza)

지원: .txt .md .csv / .docx / .xlsx / .pdf / 이미지(.png .jpg .jpeg .bmp .tiff)
"""

import os
import shutil

from masking_engine import mask_text, mask_literals, PII_BY_KEY

TEXT_EXTS = {".txt", ".md", ".csv", ".tsv", ".log", ".json"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}


def output_path(src_path, out_dir, suffix="_masked"):
    base = os.path.basename(src_path)
    name, ext = os.path.splitext(base)
    return os.path.join(out_dir, f"{name}{suffix}{ext}")


def _merge(dst_counts, more):
    for k, v in more.items():
        dst_counts[k] = dst_counts.get(k, 0) + v


def _detect(text, ner_opts):
    """ner_opts = dict(langs, want_name, want_address, threshold, exclude) 또는 None."""
    if not ner_opts:
        return set()
    langs = ner_opts.get("langs") or []
    want_name = ner_opts.get("want_name", False)
    want_address = ner_opts.get("want_address", False)
    if not (want_name or want_address) or not langs:
        return set()
    from ner_engine import detect_entities
    return detect_entities(
        text, langs, want_name, want_address,
        threshold=ner_opts.get("threshold", 0.5),
        exclude=ner_opts.get("exclude"),
    )


def _mask_str(text, keys, level, literals):
    """한 조각의 텍스트에 정규식 + NER literal 마스킹을 모두 적용."""
    out, c1 = mask_text(text, keys, level)
    out, c2 = mask_literals(out, literals, level)
    merged = {}
    _merge(merged, c1)
    _merge(merged, c2)
    return out, merged


# ---------------------------------------------------------------------------
# 텍스트 계열
# ---------------------------------------------------------------------------
def handle_text(src, dst, keys, level, ner_opts):
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    literals = _detect(content, ner_opts)
    masked, counts = _mask_str(content, keys, level, literals)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(masked)
    return counts


# ---------------------------------------------------------------------------
# Word (.docx)
# ---------------------------------------------------------------------------
def handle_docx(src, dst, keys, level, ner_opts):
    from docx import Document

    shutil.copy2(src, dst)
    doc = Document(dst)
    total = {}

    # NER은 문맥이 필요하므로 문서 전체 텍스트로 1회 탐지
    all_paras = []

    def _collect(paragraph):
        all_paras.append(paragraph)

    for p in doc.paragraphs:
        _collect(p)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    _collect(p)

    full_text = "\n".join(p.text for p in all_paras)
    literals = _detect(full_text, ner_opts)

    for p in all_paras:
        for run in p.runs:
            if run.text:
                new, c = _mask_str(run.text, keys, level, literals)
                if new != run.text:
                    run.text = new
                _merge(total, c)
    doc.save(dst)
    return total


# ---------------------------------------------------------------------------
# Excel (.xlsx)
# ---------------------------------------------------------------------------
def handle_xlsx(src, dst, keys, level, ner_opts):
    import openpyxl

    shutil.copy2(src, dst)
    wb = openpyxl.load_workbook(dst)
    total = {}

    text_cells = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value:
                    text_cells.append(cell)

    full_text = "\n".join(c.value for c in text_cells)
    literals = _detect(full_text, ner_opts)

    for cell in text_cells:
        new, c = _mask_str(cell.value, keys, level, literals)
        if new != cell.value:
            cell.value = new
        _merge(total, c)
    wb.save(dst)
    return total


# ---------------------------------------------------------------------------
# PDF — 텍스트를 실제로 제거(redaction)하고 검은 박스 처리
# ---------------------------------------------------------------------------
def handle_pdf(src, dst, keys, level, ner_opts):
    import fitz  # PyMuPDF

    doc = fitz.open(src)
    total = {}
    for page in doc:
        text = page.get_text()
        targets = {}  # 문자열 -> 라벨

        # 정규식 PII
        for key in keys:
            spec = PII_BY_KEY.get(key)
            if not spec:
                continue
            for m in spec["pattern"].finditer(text):
                targets[m.group(0)] = spec["label"]

        # NER 이름/주소
        for value, kind in _detect(text, ner_opts):
            from masking_engine import KIND_LABELS
            targets[value] = KIND_LABELS.get(kind, kind)

        for t, label in targets.items():
            rects = page.search_for(t)
            if rects:
                total[label] = total.get(label, 0) + 1
            for rect in rects:
                page.add_redact_annot(rect, fill=(0, 0, 0))
        page.apply_redactions()
    doc.save(dst, garbage=4, deflate=True)
    doc.close()
    return total


# ---------------------------------------------------------------------------
# 이미지 — OCR 로 글자 위치를 찾아 가린다
# ---------------------------------------------------------------------------
def handle_image(src, dst, keys, level, ner_opts):
    from PIL import Image, ImageDraw
    import pytesseract

    img = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(img)
    data = pytesseract.image_to_data(
        img, lang="kor+eng+jpn", output_type=pytesseract.Output.DICT
    )
    words = data["text"]
    n = len(words)
    full_text = " ".join(w for w in words if w.strip())
    literals = _detect(full_text, ner_opts)
    # NER로 찾은 이름/주소를 단어 단위로 분해(이미지에서는 단어 단위로 가림)
    literal_words = set()
    for value, _kind in literals:
        for piece in value.replace(",", " ").split():
            if piece.strip():
                literal_words.add(piece.strip())

    total = {}

    def _box(i, label):
        x, y, w, h = (data["left"][i], data["top"][i],
                      data["width"][i], data["height"][i])
        word = words[i]
        if level == "partial" and len(word) >= 2:
            # 첫 글자만 남기고 나머지를 가린다 (글자 폭 ≈ 단어폭 / 글자수)
            char_w = w / max(len(word), 1)
            x0 = int(x + char_w)            # 첫 글자 이후부터 덮기
            draw.rectangle([x0, y, x + w, y + h], fill=(0, 0, 0))
        else:
            draw.rectangle([x, y, x + w, y + h], fill=(0, 0, 0))
        total[label] = total.get(label, 0) + 1

    for i in range(n):
        word = words[i]
        if not word.strip():
            continue
        hit_label = None
        # 정규식 PII
        for key in keys:
            spec = PII_BY_KEY.get(key)
            if spec and spec["pattern"].search(word):
                hit_label = spec["label"]
                break
        # NER 이름/주소 단어
        if not hit_label and word.strip() in literal_words:
            hit_label = "이름/주소"
        if hit_label:
            _box(i, hit_label)
    img.save(dst)
    return total


# ---------------------------------------------------------------------------
# 디스패처
# ---------------------------------------------------------------------------
def process_file(src, out_dir, keys, level, ner_opts=None):
    """
    keys     : 정규식 PII key 목록
    level    : "full" / "partial"
    ner_opts : (langs, want_name, want_address) 또는 None
    반환     : (성공여부, 메시지, 사본경로 또는 None, 치환건수 dict)
    """
    ext = os.path.splitext(src)[1].lower()
    dst = output_path(src, out_dir)
    try:
        if ext in TEXT_EXTS:
            counts = handle_text(src, dst, keys, level, ner_opts)
        elif ext == ".docx":
            counts = handle_docx(src, dst, keys, level, ner_opts)
        elif ext == ".xlsx":
            counts = handle_xlsx(src, dst, keys, level, ner_opts)
        elif ext == ".pdf":
            counts = handle_pdf(src, dst, keys, level, ner_opts)
        elif ext in IMAGE_EXTS:
            counts = handle_image(src, dst, keys, level, ner_opts)
        else:
            return False, f"지원하지 않는 형식: {ext}", None, {}
        return True, "완료", dst, counts
    except ImportError as e:
        return False, f"필요한 라이브러리 미설치: {e}", None, {}
    except Exception as e:
        return False, f"오류: {e}", None, {}
