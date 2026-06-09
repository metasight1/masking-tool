# -*- coding: utf-8 -*-
"""
masking_engine.py
한국 기준 개인 민감정보를 탐지하고, 선택한 레벨로 마스킹하는 순수 로직 모듈.
외부 네트워크를 전혀 사용하지 않는 100% 로컬 처리.
"""

import re

# ---------------------------------------------------------------------------
# 1) 민감정보 유형 정의
#    - key      : 내부 식별자 (GUI 체크박스와 연결)
#    - label    : 화면에 보이는 이름
#    - pattern  : 탐지용 정규식
#    - mask_full: '완전 가리기' 시 치환 함수
#    - mask_part: '부분 가리기' 시 치환 함수
# ---------------------------------------------------------------------------

def _digits_only(s):
    return re.sub(r"\D", "", s)


# --- 완전/부분 마스킹 처리 함수들 ---------------------------------------------

def _full_block(match):
    """매치된 문자열 전체를 ● 로 덮되 구분자(- 공백)는 유지."""
    text = match.group(0)
    return "".join("●" if ch.isalnum() else ch for ch in text)


# 주민등록번호 910101-1234567  -> 부분: 910101-1******
def _rrn_part(match):
    text = match.group(0)
    d = _digits_only(text)
    if len(d) != 13:
        return _full_block(match)
    front, back = d[:6], d[6:]
    masked_back = back[0] + "●" * 6
    sep = "-" if "-" in text else ""
    return f"{front}{sep}{masked_back}"


# 휴대폰/전화 010-1234-5678 -> 부분: 010-****-5678
def _phone_part(match):
    text = match.group(0)
    parts = re.split(r"([-\s])", text)  # 구분자 보존
    nums = [p for p in parts if p.strip() and p not in ("-",)]
    # 가운데 그룹만 마스킹
    digit_groups = [i for i, p in enumerate(parts) if p.isdigit()]
    if len(digit_groups) >= 3:
        mid = digit_groups[len(digit_groups) // 2]
        parts[mid] = "●" * len(parts[mid])
        return "".join(parts)
    # 구분자가 없으면 가운데 4자리 마스킹
    d = _digits_only(text)
    if len(d) >= 8:
        return d[:3] + "●" * (len(d) - 7) + d[-4:]
    return _full_block(match)


# 이메일 hong@example.com -> 부분: h●●●@example.com
def _email_part(match):
    text = match.group(0)
    local, _, domain = text.partition("@")
    if len(local) <= 1:
        masked_local = "●"
    else:
        masked_local = local[0] + "●" * (len(local) - 1)
    return f"{masked_local}@{domain}"


# 카드/계좌 등 일반 긴 숫자 -> 부분: 앞 일부 + 마스킹 + 뒤 4자리
def _longnum_part(match):
    text = match.group(0)
    d = _digits_only(text)
    if len(d) <= 8:
        return _full_block(match)
    keep_front, keep_back = 4, 4
    masked_count = len(d) - keep_front - keep_back
    new_digits = d[:keep_front] + "●" * masked_count + d[-keep_back:]
    # 원래 구분자 패턴(4자리마다 -)이 있으면 4자리씩 끊어서 표시
    if "-" in text or " " in text:
        sep = "-" if "-" in text else " "
        chunks = [new_digits[i:i + 4] for i in range(0, len(new_digits), 4)]
        return sep.join(chunks)
    return new_digits


PII_TYPES = [
    {
        "key": "rrn",
        "label": "주민등록번호",
        # 6자리 - 1~4로 시작하는 7자리
        "pattern": re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b"),
        "mask_full": _full_block,
        "mask_part": _rrn_part,
    },
    {
        "key": "phone",
        "label": "전화번호/휴대폰",
        # 휴대폰 + 일반 지역번호(02, 0XX)
        "pattern": re.compile(
            r"\b(?:01[016789]|0\d{1,2})[-\s]?\d{3,4}[-\s]?\d{4}\b"
        ),
        "mask_full": _full_block,
        "mask_part": _phone_part,
    },
    {
        "key": "email",
        "label": "이메일 주소",
        "pattern": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
        "mask_full": _full_block,
        "mask_part": _email_part,
    },
    {
        "key": "card",
        "label": "카드번호",
        # 4-4-4-4 형태
        "pattern": re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
        "mask_full": _full_block,
        "mask_part": _longnum_part,
    },
    {
        "key": "account",
        "label": "계좌번호(일반 숫자열)",
        # 다양한 계좌 형식: 숫자 그룹이 - 로 연결된 10자리 이상
        "pattern": re.compile(r"\b\d{2,6}-\d{2,6}-\d{2,6}(?:-\d{1,6})?\b"),
        "mask_full": _full_block,
        "mask_part": _longnum_part,
    },
    {
        "key": "passport",
        "label": "여권번호",
        # 영문1자 + 숫자 8자리 (예: M12345678)
        "pattern": re.compile(r"\b[A-Z]\d{8}\b"),
        "mask_full": _full_block,
        "mask_part": _longnum_part,
    },
]

PII_BY_KEY = {t["key"]: t for t in PII_TYPES}


# ---------------------------------------------------------------------------
# 2) 텍스트 마스킹 핵심 함수
# ---------------------------------------------------------------------------

def mask_text(text, selected_keys, level="full"):
    """
    text          : 원본 문자열
    selected_keys : 마스킹할 PII 유형 key 목록 (예: ["rrn", "phone"])
    level         : "full"(완전 가리기) 또는 "partial"(부분 가리기)
    반환          : (마스킹된 문자열, {유형별 치환 건수})
    """
    if not text:
        return text, {}

    counts = {}
    result = text

    for key in selected_keys:
        spec = PII_BY_KEY.get(key)
        if not spec:
            continue
        repl = spec["mask_full"] if level == "full" else spec["mask_part"]

        n = [0]

        def _sub(m, _repl=repl, _n=n):
            _n[0] += 1
            return _repl(m)

        result = spec["pattern"].sub(_sub, result)
        if n[0]:
            counts[spec["label"]] = n[0]

    return result, counts


# ---------------------------------------------------------------------------
# 3) NER 결과(이름/주소 등 임의 문자열) 마스킹
#    정규식이 아니라 '탐지된 실제 문자열'을 그대로 찾아 가린다.
# ---------------------------------------------------------------------------

def _mask_block_str(s):
    """문자(한글/영문/숫자)는 ●로, 공백·구분자는 유지."""
    return "".join("●" if ch.isalnum() or ("가" <= ch <= "힣") else ch
                   for ch in s)


def _mask_name_partial(s):
    """이름 부분 가리기: 첫 글자만 남김 (홍길동 -> 홍●●, John -> J●●●)."""
    s = s.strip()
    if len(s) <= 1:
        return "●"
    return s[0] + _mask_block_str(s[1:])


def _mask_address_partial(s):
    """주소 부분 가리기: 첫 토큰(시/도 등 광역 단위)만 남기고 상세주소는 가림."""
    parts = s.split(" ", 1)
    if len(parts) == 1:
        # 공백이 없으면 앞 절반만 노출
        keep = max(1, len(s) // 3)
        return s[:keep] + _mask_block_str(s[keep:])
    return parts[0] + " " + _mask_block_str(parts[1])


_LITERAL_MASKERS = {
    "name": {"full": _mask_block_str, "partial": _mask_name_partial},
    "address": {"full": _mask_block_str, "partial": _mask_address_partial},
}

KIND_LABELS = {"name": "이름", "address": "주소"}


def mask_literals(text, literals, level="full"):
    """
    text     : 원본 문자열
    literals : iterable of (문자열, kind)  kind in {"name","address"}
    level    : "full" 또는 "partial"
    반환     : (마스킹된 문자열, {라벨: 건수})
    긴 문자열부터 치환해 부분 겹침 문제를 방지한다.
    """
    if not text or not literals:
        return text, {}

    counts = {}
    result = text
    # 중복 제거 + 길이 내림차순
    uniq = sorted(set(literals), key=lambda x: len(x[0]), reverse=True)

    for value, kind in uniq:
        if not value:
            continue
        masker = _LITERAL_MASKERS.get(kind)
        if not masker:
            continue
        repl_fn = masker["full"] if level == "full" else masker["partial"]
        replacement = repl_fn(value)
        pattern = re.compile(re.escape(value))

        n = [0]

        def _sub(m, _rep=replacement, _n=n):
            _n[0] += 1
            return _rep

        result, num = pattern.subn(_sub, result)
        if num:
            label = KIND_LABELS.get(kind, kind)
            counts[label] = counts.get(label, 0) + num

    return result, counts


if __name__ == "__main__":
    sample = (
        "홍길동 주민번호 910101-1234567, 휴대폰 010-1234-5678,\n"
        "이메일 hong@example.com, 카드 1234-5678-9012-3456,\n"
        "계좌 110-234-567890, 여권 M12345678, 집전화 02-123-4567"
    )
    all_keys = [t["key"] for t in PII_TYPES]
    print("=== 원본 ===")
    print(sample)
    print("\n=== 완전 가리기 ===")
    out, c = mask_text(sample, all_keys, "full")
    print(out, "\n", c)
    print("\n=== 부분 가리기 ===")
    out, c = mask_text(sample, all_keys, "partial")
    print(out, "\n", c)
