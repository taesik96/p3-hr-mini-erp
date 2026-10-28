# =========================================================
#  임금명세서 (S13) — 저장된 급여 회차에서 사원 한 명분을 모아 화면·PDF로 만든다
#  기재사항: 근로기준법 제48조 제2항, 시행령 제27조의2 (R10) [원문 확인 필요]
# =========================================================

import logging
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from erp import db, payroll, schedule

logging.getLogger("fontTools.subset").setLevel(logging.ERROR)    # 글꼴 일부만 넣을 때 나오는 경고 끄기

# 한글 글꼴: 이 PC는 맑은 고딕, Streamlit Cloud는 packages.txt의 fonts-nanum
FONTS = [
    (Path("C:/Windows/Fonts/malgun.ttf"), Path("C:/Windows/Fonts/malgunbd.ttf")),
    (Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"), Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf")),
]

# R10 기재사항 → 명세서 어디에 들어가는지
REQUIRED = [
    ("근로자를 특정할 수 있는 정보 (성명·생년월일·사원번호 등)", "근로자 정보 — 성명·사번·부서 (생년월일은 저장하지 않아 사번으로 특정)"),
    ("임금지급일", "머리말 지급일"),
    ("임금 총액", "지급 총액"),
    ("임금 구성항목별 금액", "지급 내역 — 항목별 금액"),
    ("출근일수·시간 등에 따라 달라지는 항목의 계산방법 (연장·야간·휴일근로 시간 수 포함)", "지급 내역 계산 방법 + 근로시간 표"),
    ("공제 항목별 금액과 총액", "공제 내역 — 항목별 금액, 공제 총액"),
]


def font():
    for regular, bold in FONTS:
        if regular.exists():
            return regular, bold if bold.exists() else regular
    return None


def data(run_id, emp_no):
    """명세서 한 장에 들어갈 내용"""
    run = db.query("SELECT * FROM payroll_run WHERE run_id = ?", (int(run_id),)).iloc[0]
    emp = db.employees().set_index("emp_no").loc[emp_no]
    lines = payroll.saved_lines(run_id)
    lines = lines[lines["사번"] == emp_no]
    year, month = int(run["pay_month"][:4]), int(run["pay_month"][5:])
    hours = db.query("""
        SELECT SUM(regular_h) AS 기본, SUM(overtime_h) AS 연장, SUM(night_h) AS 야간,
               SUM(holiday_h) AS "휴일 8시간 이내", SUM(holiday_over8_h) AS "휴일 8시간 초과"
          FROM work_summary WHERE emp_no = ? AND work_date BETWEEN ? AND ?""",
                     (emp_no, *schedule.month_range(year, month))).iloc[0]
    pay = lines[lines["구분"] == "지급"]
    deduct = lines[lines["구분"] == "공제"]
    return dict(
        company=db.query("SELECT name FROM company")["name"][0], year=year, month=month,
        pay_date=run["pay_date"], status=run["status"], closed_at=run["closed_at"],
        emp_no=emp_no, name=emp["name"], dept=emp["dept"], rank=emp["rank"], pay_type=emp["pay_type"],
        hours={k: payroll.hm((v or 0)) for k, v in hours.items()},
        pay=list(pay[["항목", "금액", "계산 근거"]].itertuples(index=False, name=None)),
        deduct=list(deduct[["항목", "금액", "계산 근거"]].itertuples(index=False, name=None)),
        pay_total=int(pay["금액"].sum()), deduct_total=int(deduct["금액"].sum()),
        net=int(pay["금액"].sum() - deduct["금액"].sum()))


# ---- PDF ----

class _Slip(FPDF):
    def footer(self):
        self.set_y(-14)
        self.set_font("ko", size=7)
        self.set_text_color(120)
        self.cell(0, 4, "(가상) 포트폴리오 예시 데이터 · 소득세: 근로소득 간이세액표(2026.3.1 지급분부터) · "
                        "기재사항: 근로기준법 제48조 제2항, 시행령 제27조의2", align="C")


def _page(pdf, d):
    pdf.add_page()
    pdf.set_text_color(0)
    pdf.set_font("ko", "B", 18)
    pdf.cell(0, 10, "임금명세서", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("ko", size=9)
    pdf.cell(0, 6, f"{d['company']} · 귀속 {d['year']}년 {d['month']}월 · 지급일 {d['pay_date']}",
             align="C", new_x="LMARGIN", new_y="NEXT")
    if d["status"] != "확정":
        pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 6, "확정 전 (작성중) — 지급 전 검토용", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
    pdf.ln(3)

    head = FontFace(emphasis="BOLD", fill_color=(235, 238, 242))

    def section(title):
        pdf.set_font("ko", "B", 11)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("ko", size=9)

    section("근로자 정보")
    with pdf.table(col_widths=(1, 2, 1, 2), first_row_as_headings=False, line_height=6) as t:
        for row in [("성명", d["name"], "사번", d["emp_no"]), ("부서", d["dept"], "직급", f"{d['rank']} ({d['pay_type']}제)")]:
            r = t.row()
            for i, v in enumerate(row):
                r.cell(v, style=head if i % 2 == 0 else None)
    pdf.ln(2)

    section("근로시간 (근태 확정값)")
    with pdf.table(headings_style=head, line_height=6, text_align="CENTER") as t:
        t.row(list(d["hours"]))
        t.row(list(d["hours"].values()))
    pdf.ln(2)

    for title, rows, label, amount in [("지급 내역", d["pay"], "지급 총액", d["pay_total"]),
                                       ("공제 내역", d["deduct"], "공제 총액", d["deduct_total"])]:
        section(title)
        with pdf.table(col_widths=(22, 18, 60), headings_style=head, line_height=5.5,
                       text_align=("LEFT", "RIGHT", "LEFT")) as t:
            t.row(["항목", "금액(원)", "계산 방법"])
            for item, amt, basis in rows:
                t.row([item, f"{amt:,}", (basis or "").replace("−", "-")])     # 맑은 고딕에 없는 빼기 기호
            t.row([label, f"{amount:,}", ""], style=head)
        pdf.ln(2)

    pdf.set_font("ko", "B", 13)
    pdf.cell(0, 10, f"실지급액  {d['net']:,}원", align="R", new_x="LMARGIN", new_y="NEXT")


def pdf_bytes(run_id, emp_nos):
    """사원 여러 명이면 한 파일에 한 장씩"""
    f = font()
    if f is None:
        raise RuntimeError("한글 글꼴을 찾지 못했습니다 (맑은 고딕 또는 나눔고딕 필요)")
    pdf = _Slip(format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_font("ko", "", str(f[0]))
    pdf.add_font("ko", "B", str(f[1]))
    for emp in emp_nos:
        _page(pdf, data(run_id, emp))
    return bytes(pdf.output())
