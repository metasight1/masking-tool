#!/bin/bash
# 더블클릭으로 실행하는 macOS 런처.
# 최초 1회는 라이브러리를 설치하고, 이후에는 바로 프로그램을 띄웁니다.

cd "$(dirname "$0")"

# pip 바이트컴파일 단계의 인코딩 오류 방지 + Tk 경고 숨김
export PYTHONIOENCODING=utf-8
export TK_SILENCE_DEPRECATION=1

echo "==================================================="
echo "  개인정보 마스킹 도구"
echo "==================================================="

# python3 확인
if ! command -v python3 >/dev/null 2>&1; then
  echo "[오류] python3 가 설치되어 있지 않습니다."
  echo "       https://www.python.org 에서 Python 3 를 설치한 뒤 다시 실행하세요."
  read -n 1 -s -r -p "아무 키나 누르면 닫힙니다..."
  exit 1
fi

# 가상환경(.venv) 준비
if [ ! -d ".venv" ]; then
  echo "최초 설정: 가상환경을 만듭니다..."
  python3 -m venv .venv
fi
PIP="./.venv/bin/pip"
PY="./.venv/bin/python"
$PIP install --upgrade pip >/dev/null 2>&1

# 설치 완료 표시 파일
CORE_FLAG=".venv/.core_installed"
NER_FLAG=".venv/.ner_installed"

# 1) 핵심 라이브러리 (필수) — 텍스트/Word/Excel/PDF/이미지 처리
if [ ! -f "$CORE_FLAG" ]; then
  echo "필수 라이브러리를 설치합니다... (1~2분)"
  # --no-compile : 일부 패키지의 바이트컴파일 충돌을 피한다
  if $PIP install --no-compile python-docx openpyxl PyMuPDF Pillow pytesseract; then
    touch "$CORE_FLAG"
  else
    echo "[오류] 필수 라이브러리 설치에 실패했습니다. 인터넷 연결을 확인하세요."
    read -n 1 -s -r -p "아무 키나 누르면 닫힙니다..."
    exit 1
  fi
fi

# 2) 이름·주소 인식(gliner) — 선택. 실패해도 번호류 마스킹은 동작.
if [ ! -f "$NER_FLAG" ]; then
  echo "이름·주소 인식 엔진(gliner)을 설치합니다... (PyTorch 포함, 용량이 커서 몇 분 걸릴 수 있음)"
  if $PIP install --no-compile gliner; then
    touch "$NER_FLAG"
    echo "gliner 설치 완료."
  else
    echo "[경고] gliner 설치에 실패했습니다."
    echo "       번호류(주민번호/전화/이메일/카드) 마스킹은 그대로 사용할 수 있습니다."
    echo "       이름·주소 인식이 필요하면 나중에 아래 명령으로 다시 시도하세요:"
    echo "       PYTHONIOENCODING=utf-8 ./.venv/bin/pip install --no-compile gliner"
  fi
fi

echo "프로그램을 실행합니다..."
$PY masking_app.py

read -n 1 -s -r -p "창을 닫으려면 아무 키나 누르세요..."
