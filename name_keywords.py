# -*- coding: utf-8 -*-
"""
name_keywords.py
'이름', '성명', 'Name', '氏名' 같은 항목명(라벨) 바로 뒤나 옆 칸에 적힌 값을
이름으로 인식한다. AI 모델(GLiNER)이 놓치는 이름을 보강하며, 모델이 설치되어
있지 않아도 동작한다. 100% 로컬 정규식 처리.

인식하는 형태
  - 같은 줄  : "성명: 홍길동", "이름 홍길동", "Name: John Smith", "氏名：山田 太郎"
  - 다음 줄  : "성명\\n홍길동"  (Word 표·PDF 에서 칸이 줄바꿈으로 나뉠 때)
  - 문장     : "성함은 홍길동입니다", "예약자는 김철수 님"
  - 표(엑셀·Word 표·CSV)
      · 옆 칸   : | 성명 | 홍길동 | 생년월일 | ... |
      · 아래 칸 : | 성명 | 연락처 |   다음 행들 → | 홍길동 | ... |

핵심 함수
  - find_names_in_text(text)  -> set[str]
  - find_names_in_table(rows) -> set[str]   rows: [[셀 문자열, ...], ...]
"""

import re

# ---------------------------------------------------------------------------
# 1) 항목명(라벨) 목록
# ---------------------------------------------------------------------------
KO_LABELS = [
    "이름", "성명", "성함", "한글\\s*성명", "한글\\s*이름", "영문\\s*성명", "영문\\s*이름",
    "고객\\s*(?:명|이름|성명)", "회원\\s*(?:명|이름|성명)",
    "예약자\\s*(?:명|이름|성명)?", "신청자\\s*(?:명|이름|성명)?",
    "주문자\\s*(?:명|이름|성명)?", "구매자\\s*(?:명|이름|성명)?",
    "수령인\\s*(?:명|이름|성명)?", "수령자\\s*(?:명|이름|성명)?", "수취인\\s*(?:명|이름|성명)?",
    "받는\\s*(?:분|사람)", "보내는\\s*(?:분|사람)",
    "담당자\\s*(?:명|이름|성명)?", "대표자\\s*(?:명|이름|성명)?", "대표\\s*이사",
    "환자\\s*(?:명|이름|성명)", "보호자\\s*(?:명|이름|성명)?",
    "투숙객\\s*(?:명|이름|성명)?", "숙박자\\s*(?:명|이름|성명)?",
    "탑승객\\s*(?:명|이름|성명)?", "탑승자\\s*(?:명|이름|성명)?",
    "승객\\s*(?:명|이름|성명)?", "여행자\\s*(?:명|이름|성명)?",
    "계약자\\s*(?:명|이름|성명)?", "피보험자\\s*(?:명|이름|성명)?",
    "예금주\\s*(?:명|이름|성명)?", "명의자", "작성자\\s*(?:명|이름|성명)?",
    "성\\s*/\\s*이름", "성\\s*/\\s*명",
]
EN_LABELS = [
    "full\\s+name", "first\\s+name", "last\\s+name", "given\\s+names?", "surname",
    "family\\s+name", "middle\\s+name",
    "passenger(?:\\s+name)?", "guest(?:\\s+name)?", "customer(?:\\s+name)?",
    "traveller(?:\\s+name)?", "traveler(?:\\s+name)?",
    "patient(?:\\s+name)?", "applicant(?:\\s+name)?", "recipient(?:\\s+name)?",
    "account\\s+holder(?:\\s+name)?", "card\\s*holder(?:\\s+name)?",
    "name\\s+of\\s+(?:passenger|guest|applicant|holder)",
    "contact\\s+(?:name|person)", "booker(?:\\s+name)?", "lead\\s+guest",
    "name",
]
JA_LABELS = [
    "氏名", "お名前", "名前", "姓名", "ご氏名", "フルネーム",
    "予約者(?:名|氏名)?", "申込者(?:名|氏名)?", "宿泊者(?:名|氏名)?", "ご宿泊者(?:名|氏名)?",
    "搭乗者(?:名|氏名)?", "受取人(?:名|氏名)?", "お届け先(?:氏名)?", "担当者(?:名|氏名)?",
    "代表者(?:名|氏名)?", "契約者(?:名|氏名)?", "口座名義(?:人)?", "名義人",
]

# 공백만 두고 값이 와도 되는 '확실한' 라벨 (이름/성명/OO명 등).
# 그 외(승객, 담당자, Guest ...)는 '승객 안내', 'Guest Wi-Fi' 같은 일반 문장과
# 헷갈리므로 콜론(:)·탭·줄바꿈 뒤에 오거나, 이름 뒤에 '님/씨'가 붙을 때만 인정한다.
_STRONG_KO = re.compile(r"(?:이름|성명|성함|명)$")
_STRONG_JA = {"氏名", "お名前", "名前", "姓名", "ご氏名", "フルネーム"}


def _sorted_alt(labels):
    return "|".join(sorted(labels, key=len, reverse=True))


_OPT_SUFFIX = "\\s*(?:명|이름|성명)?"
_OPT_SUFFIX_JA = "(?:名|氏名)?"
_STRONG_LABELS, _WEAK_KO_JA = [], []
for _l in KO_LABELS + JA_LABELS:
    if _l.endswith(_OPT_SUFFIX):           # '예약자(명)' → 예약자명=확실, 예약자=애매
        _base = _l[: -len(_OPT_SUFFIX)]
        _STRONG_LABELS.append(_base + "\\s*(?:명|이름|성명)")
        _WEAK_KO_JA.append(_base)
    elif _l.endswith(_OPT_SUFFIX_JA):
        _base = _l[: -len(_OPT_SUFFIX_JA)]
        _STRONG_LABELS.append(_base + "(?:名|氏名)")
        _WEAK_KO_JA.append(_base)
    elif _l in _STRONG_JA or _STRONG_KO.search(_l.rstrip(")")):
        _STRONG_LABELS.append(_l)
    else:
        _WEAK_KO_JA.append(_l)

_STRONG_RE = "(?:" + _sorted_alt(_STRONG_LABELS) + ")"
_WEAK_RE = ("(?:" + _sorted_alt(_WEAK_KO_JA) + "|(?i:" + _sorted_alt(EN_LABELS) + "))")
_LABEL_RE = "(?:" + _sorted_alt(KO_LABELS + JA_LABELS) + "|(?i:" + _sorted_alt(EN_LABELS) + "))"

# 라벨 앞에 붙으면 '사람 이름'이 아닌 항목 (회사 이름, 파일 이름, Hotel Name 등)
_NOT_PERSON_PREFIX = [
    "회사", "상호", "업체", "법인", "기관", "단체", "학교", "병원", "상품", "제품", "모델",
    "파일", "폴더", "호텔", "숙소", "매장", "지점", "은행", "항공사", "브랜드", "도메인",
    "서비스", "프로그램", "앱", "계정", "사용자", "아이디", "행사", "과정", "강의", "프로젝트",
    "항목", "메뉴", "약품", "질병", "부서", "직책", "도시", "국가", "지역", "건물", "단지",
    "company", "business", "file", "folder", "hotel", "property", "product", "item",
    "brand", "host", "domain", "user", "username", "model", "device", "project",
    "event", "store", "shop", "bank", "airline", "service", "app", "account",
    "street", "city", "country", "building", "school", "organization", "org", "course",
    "会社", "ホテル", "商品", "ファイル", "施設", "店舗", "銀行", "航空会社", "ユーザー",
]

# 값으로 오면 이름이 아닌 단어 (다른 항목명, 안내 문구 등)
_NOT_NAME_VALUES = {
    # 한국어
    "이름", "성명", "성함", "주소", "전화", "전화번호", "연락처", "휴대폰", "핸드폰", "이메일",
    "생년월일", "생일", "나이", "연령", "성별", "남성", "여성", "남자", "여자", "국적", "직업",
    "직위", "직책", "소속", "부서", "회사", "서명", "날짜", "일자", "비고", "기타", "본인",
    "고객", "회원", "입력", "기재", "작성", "확인", "변경", "등록", "수정", "삭제", "조회",
    "없음", "미상", "미기재", "해당없음", "필수", "선택", "예시", "홍길동님", "번호",
    "주민번호", "주민등록번호", "여권번호", "계좌번호", "카드번호", "예약번호", "금액", "합계",
    "영문", "한글", "그리고", "또는", "및", "등", "란", "칸", "항목", "정보", "내용", "기준",
    "관계", "보호자", "신청자", "예약자", "수령인", "담당자", "대표자", "환자", "승객",
    "탑승객", "투숙객", "계약자", "피보험자", "예금주", "명의자", "작성자",
    "모를", "없는", "있는", "대신", "순서", "표기", "기입", "공개", "비공개", "일치",
    "불일치", "표시", "철자", "동일", "동반", "안내", "변경시", "란에", "칸에", "부분",
    "전체", "모두", "각각", "까지", "부터", "마스킹", "가리기", "숨김", "생략", "미입력",
    "정정", "오류", "누락", "필드", "목록", "명단", "리스트", "검색", "정렬", "순으로",
    # 영어
    "name", "full", "first", "last", "given", "surname", "family", "middle", "mr", "mrs",
    "ms", "miss", "dr", "n/a", "na", "none", "null", "unknown", "required", "optional",
    "please", "enter", "here", "your", "the", "and", "or", "of", "to", "is", "tbd", "tba",
    "address", "phone", "tel", "email", "e-mail", "date", "dob", "birth", "age", "sex",
    "gender", "nationality", "passport", "booking", "reservation", "signature", "title",
    "male", "female", "adult", "child", "infant", "guest", "passenger", "customer",
    "number", "no", "id", "type", "status", "total", "amount",
    # 일본어
    "氏名", "名前", "お名前", "住所", "電話", "電話番号", "連絡先", "生年月日", "年齢", "性別",
    "国籍", "職業", "署名", "日付", "備考", "本人", "記入", "入力", "確認", "変更", "必須",
    "フリガナ", "ふりがな", "様",
}

# 영어 이름 뒤에 이어 붙으면 잘라낼 다음 항목명
_EN_STOP = {
    "date", "dob", "birth", "age", "sex", "gender", "phone", "tel", "mobile", "email",
    "e-mail", "address", "nationality", "passport", "booking", "reservation", "ticket",
    "seat", "flight", "class", "room", "check", "id", "no", "number", "signature",
    "title", "status", "type", "total", "amount", "adult", "child", "infant",
}

# ---------------------------------------------------------------------------
# 2) 이름 값 형태
# ---------------------------------------------------------------------------
# 한국어: '홍 길동'(성 뒤 공백) 또는 한글 덩어리(뒤에 붙은 조사·호칭은 나중에 제거)
_KO_NAME = r"[가-힣][ ][가-힣]{1,3}(?![가-힣])|[가-힣]{2,8}(?![가-힣])"
# 영어: 'John Smith', 'KIM MINSU', 'HONG/GILDONG MR', 'O'Neil', 'Mary-Jane'
_EN_WORD = r"[A-Z][A-Za-z'\-\.]*"
_EN_NAME = (
    r"(?:[A-Z][A-Z'\-]+\s*/\s*[A-Z][A-Z'\- ]*[A-Z]"            # SURNAME/GIVEN (항공권)
    r"|" + _EN_WORD + r"(?:[ \t]" + _EN_WORD + r"){0,4})"
)
# 일본어: 한자·가타카나 1~6자 (+ 공백 + 1~6자). 뒤의 '様', 'さん'은 나중에 제거
_JA_NAME = r"[一-龥々ァ-ヶー]{1,6}(?:[ 　][一-龥々ァ-ヶー]{1,6})?"

_PAREN = r"(?:\s*\([^)\n]{0,15}\))?"              # '성명(한글)' 같은 괄호 설명
# 확실한 라벨: 공백·콜론·'은/는' 뒤, 줄바꿈 1번까지 허용
_SEP_STRONG = _PAREN + r"[ \t]*(?:[:：=]|은|는|は|이란)?[ \t]*(?:\n[ \t]*)?"
# 애매한 라벨: 반드시 콜론·탭·줄바꿈 중 하나가 있어야 함
_SEP_WEAK = _PAREN + r"(?:[ \t]*[:：=][ \t]*(?:\n[ \t]*)?|\t+|[ \t]*\n[ \t]*)"
# 애매한 라벨이라도 '예약자 박민수 님'처럼 호칭이 붙으면 인정
_SEP_WEAK_HONOR = _PAREN + r"[ \t]*(?:은|는)?[ \t]*"

_VALUE = (
    r"(?:(?P<ko>" + _KO_NAME + r")"
    r"|(?P<en>" + _EN_NAME + r")"
    r"|(?P<ja>" + _JA_NAME + r"))"
)


def _rx(label_re, sep, value=_VALUE):
    return re.compile(r"(?P<label>" + label_re + r")" + sep + value, re.MULTILINE)


_TEXT_RES = [
    _rx(_STRONG_RE, _SEP_STRONG),
    _rx(_WEAK_RE, _SEP_WEAK),
    _rx(_WEAK_RE, _SEP_WEAK_HONOR,
        r"(?P<ko>[가-힣]{2,4})[ ]?(?=님|씨)"),
]

# 한글 값 뒤에 붙는 말 (여러 글자 → 항상 제거)
_KO_SUFFIX_MULTI = ["고객님", "회원님", "님께서", "입니다", "이에요", "이라고", "라고",
                    "님께", "님이", "님은", "님의", "님을", "님", "씨", "이고", "이며",
                    "이다", "예요", "에게", "께서", "께"]
# 한 글자 조사 → 4글자 이상일 때만 제거 ('이가은' 같은 3글자 이름 보호)
_KO_SUFFIX_ONE = ["을", "를", "이", "가", "의", "은", "는", "도", "와", "과", "로"]


def _clean_ko(value):
    v = value.strip()
    if " " in v:
        return v
    changed = True
    while changed:
        changed = False
        for suf in _KO_SUFFIX_MULTI:
            if v.endswith(suf) and len(v) - len(suf) >= 2:
                v = v[: -len(suf)]
                changed = True
                break
    if len(v) >= 4 and v[-1] in _KO_SUFFIX_ONE:
        v = v[:-1]
    return v if 2 <= len(v) <= 4 else ""


def _clean_ja(value):
    v = value.strip()
    for suf in ("様", "殿", "さん"):
        if v.endswith(suf) and len(v) > len(suf) + 1:
            v = v[: -len(suf)].strip()
    return v


_KO_FULL = re.compile(r"[가-힣]{2,4}|[가-힣]\s[가-힣]{1,3}")
_EN_FULL = re.compile(_EN_NAME + r"(?:\s+(?:MR|MRS|MS|MISS|MSTR|DR))?")
_JA_FULL = re.compile(_JA_NAME)
_LABEL_FULL = re.compile(r"\s*" + _LABEL_RE + r"\s*(?:\([^)]{0,15}\))?\s*[:：]?\s*")


# ---------------------------------------------------------------------------
# 3) 보조 함수
# ---------------------------------------------------------------------------
def _prefix_blocked(text, label_start):
    """라벨 바로 앞 단어가 '회사', 'Hotel' 등이면 사람 이름 항목이 아니다."""
    before = text[max(0, label_start - 20):label_start]
    before = before.rstrip(" \t_-·").lower()
    return any(before.endswith(p) for p in _NOT_PERSON_PREFIX)


def _clean_en(value):
    """영어 이름 뒤에 붙은 다음 항목명(Date, Phone ...)과 호칭을 잘라낸다."""
    if "/" in value:
        value = re.sub(r"\s+(?:MR|MRS|MS|MISS|MSTR|DR)\.?$", "", value.strip())
        return value.strip()
    tokens = value.split()
    kept = []
    for t in tokens:
        if t.lower().strip(".:") in _EN_STOP:
            break
        kept.append(t)
    while kept and kept[-1].lower().strip(".") in {"mr", "mrs", "ms", "miss", "dr", "mstr"}:
        kept.pop()
    return " ".join(kept)


def _valid(value):
    v = value.strip()
    if len(v) < 2:
        return False
    low = v.lower()
    if low in _NOT_NAME_VALUES or v in _NOT_NAME_VALUES:
        return False
    # 한글 값의 끝에 붙은 조사·호칭 제거 후 재확인 (예: '고객님')
    if any(w and w in _NOT_NAME_VALUES for w in v.lower().split()):
        # 'John Name' 처럼 일부만 금지어면 단어 전체가 금지어일 때만 막는다
        if all(w in _NOT_NAME_VALUES for w in v.lower().split()):
            return False
    return True


# ---------------------------------------------------------------------------
# 4) 공개 함수
# ---------------------------------------------------------------------------
def find_names_in_text(text):
    """텍스트에서 '라벨 + 이름' 형태를 찾아 이름 문자열 집합을 반환."""
    found = set()
    if not text:
        return found
    for rx in _TEXT_RES:
        for m in rx.finditer(text):
            if _prefix_blocked(text, m.start("label")):
                continue
            g = m.groupdict()
            if g.get("ko"):
                val = _clean_ko(g["ko"])
            elif g.get("en"):
                val = _clean_en(g["en"])
            else:
                val = _clean_ja(g.get("ja") or "")
            val = val.strip()
            if val and _valid(val):
                found.add(val)
    return found


def _is_label_cell(cell):
    """셀 전체가 이름 항목명인지 ('성명', '이름:', 'Guest Name', '氏名')."""
    if not cell or len(cell) > 30:
        return False
    m = _LABEL_FULL.fullmatch(cell)
    if not m:
        return False
    return not _prefix_blocked(cell, len(cell) - len(cell.lstrip()) + 0) and \
        not any(cell.strip().lower().startswith(p) for p in _NOT_PERSON_PREFIX)


def _name_from_cell(cell):
    """셀 전체가 이름처럼 생겼으면 그 이름을, 아니면 None."""
    if not cell:
        return None
    v = cell.strip()
    if not v or len(v) > 40:
        return None
    if _KO_FULL.fullmatch(v):
        return v if _valid(v) else None
    if _EN_FULL.fullmatch(v):
        val = _clean_en(v)
        return val if val and _valid(val) and val == _clean_en(val) else None
    if _JA_FULL.fullmatch(v):
        v = _clean_ja(v)
        return v if _valid(v) else None
    return None


def find_names_in_table(rows):
    """
    rows : [[셀 문자열, ...], ...]  (엑셀 시트, Word 표, CSV)
    '성명' 같은 항목명 셀을 찾아
      - 오른쪽 칸이 이름이면 그것만 (가로형 양식)
      - 아니면 같은 열의 아래 칸들 (세로형 목록)
    을 이름으로 본다.
    """
    found = set()
    if not rows:
        return found
    grid = [[(c or "").strip() if isinstance(c, str) else "" for c in r] for r in rows]
    for ri, row in enumerate(grid):
        for ci, cell in enumerate(row):
            if not _is_label_cell(cell):
                continue
            # 가로형: 오른쪽의 첫 번째 비어있지 않은 칸
            right = next((c for c in row[ci + 1:] if c), None)
            name = _name_from_cell(right) if right else None
            if name:
                found.add(name)
                continue
            # 세로형: 아래 칸들 — 다른 항목명이 나오면 중단
            for below in grid[ri + 1:]:
                if ci >= len(below):
                    continue
                c = below[ci]
                if not c:
                    continue
                if _is_label_cell(c):
                    break
                name = _name_from_cell(c)
                if name:
                    found.add(name)
    return found


if __name__ == "__main__":
    samples = [
        "성명: 홍길동", "이름 김철수", "성함은 이영희입니다.", "예약자 박민수 님",
        "성명(한글) 최지우", "성명\n정우성", "Name: John Smith  Date: 2026-01-01",
        "Passenger Name: HONG/GILDONG MR", "Guest name: Mary-Jane O'Neil",
        "氏名：山田 太郎", "お名前 佐藤花子様",
        # 잡히면 안 되는 것
        "이름을 입력하세요", "회사 이름: 메타사이트", "Hotel Name: Grand Hyatt",
        "이름 주소 전화번호", "name: please enter", "File name: report",
        "성명 변경 신청", "파일이름: test", "보호자 동반 시", "Guest Wi-Fi password",
        "승객 안내", "이름 모를 꽃",
        # 추가 확인
        "이름: 홍길동, 주소: 서울", "성명 : 홍 길동", "고객명: 이순신 고객님",
        "예약자명 김연아\n연락처", "First name: Jane\nLast name: Doe", "이름 홍길동을 입력",
        "이가은", "이름 이가은", "담당자: 강감찬", "Name\tKIM MINSU", "승객\n장보고",
    ]
    for s in samples:
        print(repr(s), "->", find_names_in_text(s))
    print(find_names_in_table([["성명", "홍길동", "생년월일", "910101"],
                               ["주소", "서울시", "연락처", "010"]]))
    print(find_names_in_table([["No", "이름", "연락처"],
                               ["1", "김철수", "010-1"], ["2", "Jane Doe", "010-2"]]))
