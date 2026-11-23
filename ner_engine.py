# -*- coding: utf-8 -*-
"""
ner_engine.py
GLiNER(다국어 PII) 기반 이름/주소 인식 + 언어별 주소 정규식 보강.
한국어(ko) / 영어(en) / 일본어(ja)를 하나의 모델로 처리.
100% 로컬(모델은 최초 1회 다운로드 후 오프라인).

핵심 함수:
  - download_model()                : 최초 1회 모델 다운로드(인터넷 필요)
  - detect_entities(text, langs, want_name, want_address)
        -> set[(matched_string, kind)]   kind in {"name", "address"}
        ('이름/성명' 항목명 옆의 값도 이름으로 인식 → name_keywords.py)
  - engine_available()              : gliner 설치 여부
"""

import re

SUPPORTED_LANGS = ["ko", "en", "ja"]

# GLiNER 다국어 PII 모델 (사람/주소 등 개인정보에 특화, 다국어 지원)
MODEL_NAME = "urchade/gliner_multi_pii-v1"
THRESHOLD = 0.5            # 기본 임계값 (낮출수록 더 많이 잡지만 오탐↑)
_MODEL = None             # 로딩된 GLiNER 모델 캐시

# GLiNER에 요청할 라벨 (좁게 잡아야 공항·도시명 같은 일반 지명 과다탐지를 막는다)
#  · 이름  : "person" 만
#  · 주소  : "address" 만 (※ "location"은 공항/도시명까지 잡으므로 일부러 제외)
NAME_LABELS_REQ = ["person"]
ADDR_LABELS_REQ = ["address"]

# 기본 제외 단어 (이 단어를 '포함'하는 탐지결과는 마스킹하지 않음).
# 항공권/이티켓에서 공항·항공사 등이 이름·주소로 오탐되는 것을 막는다.
DEFAULT_EXCLUDE = [
    "공항", "국제공항", "공항점", "항공", "터미널", "게이트",
    "airport", "terminal", "gate", "airlines", "air",
]


# ---------------------------------------------------------------------------
# 언어별 '전체 주소' 정규식 (모델이 번지/상세주소를 놓칠 때 보강)
# ---------------------------------------------------------------------------
ADDRESS_PATTERNS = {
    # 한국어: (시/도) (시/군/구) (읍/면/동/로/길) + 번지/호
    "ko": re.compile(
        r"(?:[가-힣]{2,}(?:특별자치도|특별자치시|특별시|광역시|도)\s*)?"
        r"[가-힣]{1,10}(?:시|군|구)\s*"
        r"[가-힣0-9]{1,15}(?:읍|면|동|리|가|로|길)\s*"
        r"\d[\d\-]*(?:번지|번길|호|층)?"
    ),
    # 일본어: (都道府県) 市区町村 ... 丁目/番地/号  (ひらがな 제외로 조사 과다매칭 방지)
    "ja": re.compile(
        r"(?:[一-龥ァ-ヶ]{2,4}[都道府県])?"
        r"[一-龥ァ-ヶ]{1,8}[市区町村]"
        r"[一-龥ァ-ヶ0-9０-９]*"
        r"(?:[0-9０-９]+丁目)?(?:[0-9０-９]+番地?)?(?:[0-9０-９]+号)?"
    ),
    # 영어: 123 Main Street, City ST 12345
    "en": re.compile(
        r"\d{1,6}\s+(?:[A-Z][A-Za-z.]+\s+){1,4}"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|"
        r"Court|Ct|Way|Place|Pl|Terrace|Ter|Highway|Hwy)\b"
        r"(?:,?\s+[A-Z][A-Za-z]+)?(?:,?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?)?",
        re.IGNORECASE,
    ),
}


# ---------------------------------------------------------------------------
# 모델 로딩
# ---------------------------------------------------------------------------
def download_model():
    """최초 1회: GLiNER 모델을 내려받는다(인터넷 필요)."""
    from gliner import GLiNER
    GLiNER.from_pretrained(MODEL_NAME)


def _get_model():
    global _MODEL
    if _MODEL is None:
        from gliner import GLiNER
        _MODEL = GLiNER.from_pretrained(MODEL_NAME)
    return _MODEL


def _chunks(text, size=350):
    """GLiNER 입력 길이 제한에 맞춰 텍스트를 줄/길이 단위로 자른다."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) <= size:
            yield line
        else:
            for i in range(0, len(line), size):
                yield line[i:i + size]


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------
def _is_excluded(val, exclude_terms):
    """탐지값이 제외 단어를 포함하면 True (대소문자 무시)."""
    low = val.lower()
    for term in exclude_terms:
        term = term.strip().lower()
        if term and term in low:
            return True
    return False


def detect_entities(text, langs, want_name=True, want_address=True,
                    threshold=THRESHOLD, exclude=None, use_default_exclude=True,
                    tables=None, use_model=True):
    """
    text          : 분석할 전체 텍스트
    langs         : ["ko","en","ja"] 중 선택 (주소 정규식 보강용)
    threshold     : 탐지 임계값 (높을수록 적게/정확히, 낮을수록 많이 잡음)
    exclude       : 마스킹에서 제외할 단어 목록(부분일치)
    tables        : 표 데이터 [[[셀, ...], ...], ...] — '성명' 칸 옆/아래 이름 인식용
    use_model     : False 면 GLiNER 없이 '이름/성명' 항목명 기반 인식만 수행
    반환          : set[(문자열, kind)]  kind in {"name","address"}
    """
    results = set()
    if (not text or not text.strip()) and not tables:
        return results
    text = text or ""

    exclude_terms = list(exclude) if exclude else []
    if use_default_exclude:
        exclude_terms = exclude_terms + DEFAULT_EXCLUDE

    # 1) GLiNER NER (이름 + 주소) — 다국어 단일 모델
    labels = []
    if want_name:
        labels += NAME_LABELS_REQ
    if want_address:
        labels += ADDR_LABELS_REQ
    if labels and use_model and text.strip():
        try:
            model = _get_model()
            for chunk in _chunks(text):
                try:
                    ents = model.predict_entities(chunk, labels, threshold=threshold)
                except Exception:
                    continue
                for e in ents:
                    val = (e.get("text") or "").strip()
                    lab = (e.get("label") or "").lower()
                    if not val or _is_excluded(val, exclude_terms):
                        continue
                    if want_name and lab == "person":
                        results.add((val, "name"))
                    elif want_address and lab == "address":
                        results.add((val, "address"))
        except Exception:
            # 모델 미설치/로드 실패 시: 주소 정규식만이라도 적용되도록 통과
            pass

    # 2) '이름', '성명', 'Name', '氏名' 등 항목명 옆의 이름 (모델이 놓친 것 보강)
    if want_name:
        from name_keywords import find_names_in_text, find_names_in_table
        names = find_names_in_text(text)
        for rows in tables or []:
            names |= find_names_in_table(rows)
        for val in names:
            if not _is_excluded(val, exclude_terms):
                results.add((val, "name"))

    # 3) 주소 정규식 보강
    if want_address:
        for lc in langs:
            pat = ADDRESS_PATTERNS.get(lc)
            if pat:
                for m in pat.finditer(text):
                    val = m.group(0).strip()
                    if len(val) >= 4 and not _is_excluded(val, exclude_terms):
                        results.add((val, "address"))

    return results


def engine_available():
    """gliner 설치 여부 확인."""
    try:
        import gliner  # noqa
        return True
    except ImportError:
        return False


# 구버전 호환용 별칭
stanza_available = engine_available


def download_models(langs=None):
    """GUI 호환용: 언어 인자는 무시하고 단일 다국어 모델을 받는다."""
    download_model()
