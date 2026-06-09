# -*- coding: utf-8 -*-
"""
masking_app.py
개인정보 마스킹 도구 (macOS GUI) — 100% 로컬 처리.

사용법:
  - 마스킹할 파일을 추가
  - 가릴 민감정보 유형을 체크
  - 마스킹 레벨(완전/부분) 선택
  - 저장 폴더 선택 후 [마스킹 실행]
원본은 그대로 두고, 파일명에 _masked 가 붙은 사본만 생성됩니다.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from masking_engine import PII_TYPES
from file_handlers import process_file, TEXT_EXTS, IMAGE_EXTS

SUPPORTED = (
    [("모든 지원 파일",
      "*.txt *.md *.csv *.tsv *.log *.json *.docx *.xlsx *.pdf "
      "*.png *.jpg *.jpeg *.bmp *.tiff *.tif")]
)


class MaskingApp:
    def __init__(self, root):
        self.root = root
        root.title("개인정보 마스킹 도구 (로컬)")
        root.geometry("720x720")

        self.files = []
        self.out_dir = tk.StringVar(value="")
        self.level = tk.StringVar(value="full")
        self.type_vars = {}          # 정규식 PII
        self.name_var = tk.BooleanVar(value=True)   # 이름(NER)
        self.addr_var = tk.BooleanVar(value=True)   # 주소(NER)
        self.lang_vars = {           # NER 언어
            "ko": tk.BooleanVar(value=True),
            "en": tk.BooleanVar(value=True),
            "ja": tk.BooleanVar(value=False),
        }
        self.sensitivity = tk.StringVar(value="mid")   # 탐지 강도
        self.exclude_var = tk.StringVar(value="")      # 제외 단어(쉼표)

        self._build_ui()

    # ---------------- UI 구성 ----------------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # ===== 하단 고정 실행 바 (가장 먼저 배치 → 창 크기와 무관하게 항상 보임) =====
        bottom = ttk.Frame(self.root)
        bottom.pack(side="bottom", fill="x", padx=10, pady=8)
        self.run_btn = ttk.Button(bottom, text="✅  마스킹 실행", command=self.run)
        self.run_btn.pack(side="left", ipadx=12, ipady=4)
        self.status = ttk.Label(bottom, text="대기 중")
        self.status.pack(side="left", padx=12)

        # ===== 스크롤 가능한 본문 영역 (내용이 길어도 모두 접근 가능) =====
        outer = ttk.Frame(self.root)
        outer.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(win_id, width=e.width))
        # 트랙패드/마우스휠 스크롤 (macOS)
        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * e.delta), "units"))

        # 1) 파일 선택
        frm_files = ttk.LabelFrame(body, text="1. 마스킹할 파일")
        frm_files.pack(fill="both", expand=False, **pad)

        self.lst = tk.Listbox(frm_files, height=6, selectmode=tk.EXTENDED)
        self.lst.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        sb = ttk.Scrollbar(frm_files, command=self.lst.yview)
        sb.pack(side="left", fill="y", pady=8)
        self.lst.config(yscrollcommand=sb.set)

        btns = ttk.Frame(frm_files)
        btns.pack(side="left", fill="y", padx=8, pady=8)
        ttk.Button(btns, text="파일 추가", command=self.add_files).pack(fill="x", pady=2)
        ttk.Button(btns, text="선택 제거", command=self.remove_selected).pack(fill="x", pady=2)
        ttk.Button(btns, text="전체 비우기", command=self.clear_files).pack(fill="x", pady=2)

        # 2) 민감정보 유형
        frm_types = ttk.LabelFrame(body, text="2. 가릴 민감정보 유형 (체크)")
        frm_types.pack(fill="x", **pad)
        inner = ttk.Frame(frm_types)
        inner.pack(fill="x", padx=8, pady=8)
        for i, t in enumerate(PII_TYPES):
            var = tk.BooleanVar(value=True)
            self.type_vars[t["key"]] = var
            ttk.Checkbutton(inner, text=t["label"], variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=6, pady=3
            )
        sel = ttk.Frame(frm_types)
        sel.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(sel, text="전체 선택", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(sel, text="전체 해제", command=lambda: self._set_all(False)).pack(side="left", padx=6)

        # 2-2) 이름/주소 (NER) + 언어
        frm_ner = ttk.LabelFrame(body, text="2-2. 이름·주소 자동 인식 (GLiNER · 한/영/일)")
        frm_ner.pack(fill="x", **pad)
        rowa = ttk.Frame(frm_ner)
        rowa.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Checkbutton(rowa, text="이름", variable=self.name_var).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(rowa, text="주소", variable=self.addr_var).pack(side="left", padx=(0, 20))
        ttk.Label(rowa, text="인식 언어:").pack(side="left")
        ttk.Checkbutton(rowa, text="한국어", variable=self.lang_vars["ko"]).pack(side="left")
        ttk.Checkbutton(rowa, text="English", variable=self.lang_vars["en"]).pack(side="left")
        ttk.Checkbutton(rowa, text="日本語", variable=self.lang_vars["ja"]).pack(side="left")
        # 탐지 강도(민감도)
        rowc = ttk.Frame(frm_ner)
        rowc.pack(fill="x", padx=8, pady=(0, 2))
        ttk.Label(rowc, text="탐지 강도:").pack(side="left")
        ttk.Radiobutton(rowc, text="약하게(정확)", variable=self.sensitivity,
                        value="low").pack(side="left")
        ttk.Radiobutton(rowc, text="보통", variable=self.sensitivity,
                        value="mid").pack(side="left")
        ttk.Radiobutton(rowc, text="강하게(많이)", variable=self.sensitivity,
                        value="high").pack(side="left")
        ttk.Label(rowc, text="  ← 공항·일반명사가 가려지면 '약하게'로",
                  foreground="#666").pack(side="left")

        # 제외 단어
        rowd = ttk.Frame(frm_ner)
        rowd.pack(fill="x", padx=8, pady=(0, 2))
        ttk.Label(rowd, text="제외 단어(쉼표로 구분):").pack(side="left")
        ttk.Entry(rowd, textvariable=self.exclude_var).pack(
            side="left", fill="x", expand=True, padx=6)

        rowb = ttk.Frame(frm_ner)
        rowb.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Button(rowb, text="이름·주소 모델 준비 (최초 1회)",
                   command=self.prepare_models).pack(side="left")
        ttk.Label(
            rowb,
            text="※ 최초 1회만 인터넷 다운로드. 이후 오프라인. (공항·항공 등은 기본 제외)",
            foreground="#666",
        ).pack(side="left", padx=8)

        # 3) 마스킹 레벨
        frm_level = ttk.LabelFrame(body, text="3. 마스킹 레벨")
        frm_level.pack(fill="x", **pad)
        ttk.Radiobutton(
            frm_level, text="완전 가리기  (예: 910101-1234567 → ●●●●●●-●●●●●●●)",
            variable=self.level, value="full",
        ).pack(anchor="w", padx=10, pady=3)
        ttk.Radiobutton(
            frm_level, text="부분 가리기  (예: 910101-1234567 → 910101-1●●●●●●)",
            variable=self.level, value="partial",
        ).pack(anchor="w", padx=10, pady=3)
        ttk.Label(
            frm_level,
            text="※ PDF는 두 레벨 모두 텍스트를 완전히 삭제합니다. 이미지는 부분 가리기 시 첫 글자만 남깁니다.",
            foreground="#666",
        ).pack(anchor="w", padx=10, pady=(0, 6))

        # 4) 저장 폴더
        frm_out = ttk.LabelFrame(body, text="4. 사본 저장 폴더")
        frm_out.pack(fill="x", **pad)
        row = ttk.Frame(frm_out)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Entry(row, textvariable=self.out_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="폴더 선택", command=self.choose_out_dir).pack(side="left", padx=6)

        # 5) 로그 (본문 스크롤 영역 안)
        frm_log = ttk.LabelFrame(body, text="5. 진행 로그")
        frm_log.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(frm_log, height=7, state="disabled")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

    # ---------------- 이벤트 ----------------
    def _set_all(self, val):
        for v in self.type_vars.values():
            v.set(val)

    def add_files(self):
        paths = filedialog.askopenfilenames(title="파일 선택", filetypes=SUPPORTED)
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.lst.insert(tk.END, p)

    def remove_selected(self):
        for i in reversed(self.lst.curselection()):
            self.files.pop(i)
            self.lst.delete(i)

    def clear_files(self):
        self.files.clear()
        self.lst.delete(0, tk.END)

    def choose_out_dir(self):
        d = filedialog.askdirectory(title="사본을 저장할 폴더 선택")
        if d:
            self.out_dir.set(d)

    def _log(self, msg):
        self.log.config(state="normal")
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")

    def prepare_models(self):
        from ner_engine import engine_available
        if not engine_available():
            messagebox.showerror(
                "알림", "이름·주소 인식 엔진(gliner)이 없습니다.\n'설치_및_실행.command'로 먼저 설치하세요.")
            return
        if not messagebox.askokcancel(
            "모델 다운로드",
            "이름·주소 인식 모델(GLiNER 다국어)을 내려받습니다.\n"
            "한·영·일을 한 모델로 처리합니다.\n"
            "인터넷이 필요하며 수백 MB가 받아질 수 있습니다. 계속할까요?"):
            return
        self.run_btn.config(state="disabled")
        self.status.config(text="모델 다운로드 중...")
        self._log("모델 다운로드 시작: GLiNER 다국어 PII 모델")

        def _dl():
            try:
                from ner_engine import download_model
                download_model()
                self._log("모델 다운로드 완료.")
                msg = "완료"
            except Exception as e:
                self._log(f"모델 다운로드 실패: {e}")
                msg = f"실패: {e}"
            self.root.after(0, lambda: (
                self.run_btn.config(state="normal"),
                self.status.config(text=f"모델 준비 {msg}")))
        threading.Thread(target=_dl, daemon=True).start()

    def run(self):
        if not self.files:
            messagebox.showwarning("알림", "마스킹할 파일을 먼저 추가하세요.")
            return
        keys = [k for k, v in self.type_vars.items() if v.get()]
        want_name = self.name_var.get()
        want_addr = self.addr_var.get()
        langs = [lc for lc, v in self.lang_vars.items() if v.get()]
        if not keys and not (want_name or want_addr):
            messagebox.showwarning("알림", "가릴 항목을 최소 1개 선택하세요.")
            return
        out_dir = self.out_dir.get().strip()
        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showwarning("알림", "사본을 저장할 폴더를 선택하세요.")
            return

        ner_opts = None
        if (want_name or want_addr) and langs:
            from ner_engine import engine_available
            if not engine_available():
                if not messagebox.askokcancel(
                    "알림",
                    "이름·주소 인식 엔진(gliner)이 설치되어 있지 않습니다.\n"
                    "이름·주소 없이 번호류만 마스킹하고 계속할까요?"):
                    return
            else:
                thr = {"low": 0.7, "mid": 0.5, "high": 0.35}.get(
                    self.sensitivity.get(), 0.5)
                exclude = [w.strip() for w in self.exclude_var.get().split(",")
                           if w.strip()]
                ner_opts = {
                    "langs": langs,
                    "want_name": want_name,
                    "want_address": want_addr,
                    "threshold": thr,
                    "exclude": exclude,
                }

        self.run_btn.config(state="disabled")
        self.status.config(text="처리 중...")
        threading.Thread(
            target=self._worker,
            args=(list(self.files), out_dir, keys, self.level.get(), ner_opts),
            daemon=True,
        ).start()

    def _worker(self, files, out_dir, keys, level, ner_opts):
        ok, fail = 0, 0
        self._log(f"=== 시작: {len(files)}개 파일 / 레벨={level} ===")
        for src in files:
            success, msg, dst, counts = process_file(src, out_dir, keys, level, ner_opts)
            name = os.path.basename(src)
            if success:
                ok += 1
                summary = ", ".join(f"{k} {v}건" for k, v in counts.items()) or "탐지된 항목 없음"
                self._log(f"[성공] {name} → {os.path.basename(dst)}  ({summary})")
            else:
                fail += 1
                self._log(f"[실패] {name} : {msg}")
        self._log(f"=== 완료: 성공 {ok} / 실패 {fail} ===\n")
        self.root.after(0, self._finish, ok, fail, out_dir)

    def _finish(self, ok, fail, out_dir):
        self.run_btn.config(state="normal")
        self.status.config(text=f"완료 (성공 {ok}, 실패 {fail})")
        if ok:
            messagebox.showinfo(
                "완료", f"성공 {ok}건, 실패 {fail}건\n\n저장 위치:\n{out_dir}"
            )
        else:
            messagebox.showerror("실패", "처리된 파일이 없습니다. 로그를 확인하세요.")


def _force_redraw(root):
    """macOS 구버전 Tk(8.5)에서 창이 비어 보이는 현상 방지: 강제 리드로우."""
    try:
        root.update_idletasks()
        w, h = root.winfo_width(), root.winfo_height()
        if w < 50 or h < 50:          # 아직 배치 전이면 지정 크기 사용
            w, h = 720, 640
        root.geometry(f"{w + 1}x{h + 1}")
        root.update_idletasks()
        root.geometry(f"{w}x{h}")
        root.update_idletasks()
        root.lift()
        root.focus_force()
    except Exception:
        pass


def main():
    root = tk.Tk()

    # 1) ttk 위젯을 Tk가 직접 그리는 'clam' 테마로 강제 → 구버전 native 렌더러 버그 회피
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    root.minsize(680, 560)
    MaskingApp(root)

    # 2) 창이 뜬 직후 한 번 강제로 다시 그린다
    root.after(150, lambda: _force_redraw(root))
    root.mainloop()


if __name__ == "__main__":
    main()
