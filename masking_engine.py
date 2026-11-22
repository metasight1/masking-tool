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


# --- 키워드 기반(문맥) 탐지용 마스킹 함수 ------------------------------------
#   예약번호·PIN 처럼 형식이 제각각인 값은 "예약번호:", "PIN" 같은 키워드 뒤에
#   오는 값만 잡는다. 패턴의 (?P<val>...) 그룹만 가리고 키워드는 그대로 둔다.

def _mask_chars(s):
    return "".join("●" if ch.isalnum() else ch for ch in s)


def _ctx_full(value):
    return _mask_chars(value)


def _reservation_part(value):
    """예약번호 부분 가리기: 앞 2자리만 남김 (ABC12345 -> AB●●●●●●)."""
    if len(value) <= 4:
        return _mask_chars(value)
    return value[:2] + _mask_chars(value[2:])


def _secret_full(value):
    """PIN·비밀번호: 특수문자까지 모든 글자를 가린다 (자리수만 남음)."""
    return "●" * len(value)


def _secret_part(value):
    """PIN·비밀번호는 일부만 노출해도 위험하므로 부분 가리기도 전부 가림."""
    return _secret_full(value)


# 키워드와 값 사이 구분자: 공백, 콜론(:/：), #, 'No.', 'is', 'は' 등
_SEP = r"(?:\s*(?:[:：#=]|No\.?|is|は|은|는|:)?\s*)"

_RESERVATION_KW = (
    r"(?i:"
    r"예약\s*(?:확인\s*)?(?:번호|코드)|예매\s*(?:번호|코드)|예약\s*no\.?"
    r"|(?:booking|reservation|confirmation)\s*(?:no\.?|number|code|ref(?:erence)?|id|#)"
    r"|PNR"
    r"|予約(?:確認)?(?:番号|コード)|確認番号"
    r")"
)
# 값: 숫자가 하나 이상 섞인 영숫자 4~30자, 또는 대문자 5~8자(항공 PNR 등)
_RESERVATION_VAL = r"(?P<val>(?=[A-Za-z0-9-]*\d)[A-Za-z0-9][A-Za-z0-9-]{3,29}|[A-Z]{5,8})(?![A-Za-z0-9])"

_PIN_KW = (
    r"(?i:"
    r"PIN\s*(?:번호|코드|code|number|no\.?)?|핀\s*(?:번호|코드)"
    r"|인증\s*번호|보안\s*(?:번호|코드)|OTP|CVC|CVV|CVV2"
    r"|카드\s*비밀번호|통장\s*비밀번호|계좌\s*비밀번호"
    r"|暗証番号|認証番号|ピン(?:番号|コード)"
    r")"
)
_PIN_VAL = r"(?P<val>\d{3,8})(?!\d)"

_PASSWORD_KW = (
    r"(?i:"
    r"비밀\s*번호|비번|패스워드|암호|password|passwd|pwd|passcode"
    r"|パスワード|暗号"
    r")"
)
# 값: 공백·한글·가나·한자가 아닌 4~32자, 숫자나 특수문자가 1개 이상 포함
#      ('비밀번호변경', 'Password reset' 같은 일반 문장은 제외)
_PASSWORD_VAL = (
    r"(?P<val>(?=[^\s]*[\d!@#$%^&*()_+\-\[\]{};'\"\\|<>?/~`.])"
    r"[^\s:：=,，、。가-힣\u3040-\u30ff\u4e00-\u9fff]{4,32})"
)


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
    {
        "key": "reservation",
        "label": "예약번호",
        # '예약번호', 'Booking No.', 'PNR', '予約番号' 등 키워드 뒤의 값
        "pattern": re.compile(_RESERVATION_KW + _SEP + _RESERVATION_VAL),
        "context": True,
        "mask_full": _ctx_full,
        "mask_part": _reservation_part,
    },
    {
        "key": "pin",
        "label": "PIN·인증번호",
        # 'PIN', 'PIN코드', '인증번호', 'OTP', 'CVC', '暗証番号' 등 키워드 뒤의 숫자
        "pattern": re.compile(_PIN_KW + _SEP + _PIN_VAL),
        "context": True,
        "mask_full": _secret_full,
        "mask_part": _secret_part,
    },
    {
        "key": "password",
        "label": "비밀번호",
        # '비밀번호', 'password', 'パスワード' 등 키워드 뒤의 문자열
        "pattern": re.compile(_PASSWORD_KW + _SEP + _PASSWORD_VAL),
        "context": True,
        "mask_full": _secret_full,
        "mask_part": _secret_part,
    },
]

PII_BY_KEY = {t["key"]: t for t in PII_TYPES}


def ordered_keys(keys):
    """키워드 기반 유형을 먼저 처리해야 '예약번호 010-1234-5678' 같은 값이
    전화번호 등 다른 규칙에 먼저 먹히지 않는다."""
    keys = list(keys)
    ctx = [k for k in keys if PII_BY_KEY.get(k, {}).get("context")]
    return ctx + [k for k in keys if k not in ctx]


def find_targets(text, keys):
    """
    PDF/이미지처럼 '가릴 문자열'과 위치가 필요한 곳에서 쓰는 탐지 함수.
    반환: [(start, end, 가릴 문자열, 라벨, 전체매치문자열)]
      - 키워드 기반 유형은 값 부분만(start/end 도 값 기준)
    """
    out = []
    for key in ordered_keys(keys):
        spec = PII_BY_KEY.get(key)
        if not spec:
            continue
        for m in spec["pattern"].finditer(text):
            if spec.get("context"):
                out.append((m.start("val"), m.end("val"), m.group("val"),
                            spec["label"], m.group(0)))
            else:
                out.append((m.start(), m.end(), m.group(0), spec["label"],
                            m.group(0)))
    return out


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

    for key in ordered_keys(selected_keys):
        spec = PII_BY_KEY.get(key)
        if not spec:
            continue
        repl = spec["mask_full"] if level == "full" else spec["mask_part"]

        n = [0]

        if spec.get("context"):
            # 키워드는 남기고 값(val 그룹)만 가린다
            def _sub(m, _repl=repl, _n=n):
                _n[0] += 1
                whole, start = m.group(0), m.start()
                vs, ve = m.start("val") - start, m.end("val") - start
                return whole[:vs] + _repl(m.group("val")) + whole[ve:]
        else:
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
        "계좌 110-234-567890, 여권 M12345678, 집전화 02-123-4567\n"
        "예약번호: ABC12345, Booking Ref XYZ987, 予約番号：20261122-01, PNR KJHGFD\n"
        "PIN코드 1234, 인증번호 482913, CVC 123, 暗証番号 9876\n"
        "비밀번호: qwer!234, password=Hunter22, パスワード：abcd1234"
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
