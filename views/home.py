import pandas as pd
import streamlit as st

from erp import db, ui

st.title("다온정밀(가상) HR 미니 ERP")
st.caption("자동차 부품 가공 · 상시근로자 40명 · 주야 2교대 · 샘플 기간 2026년 9월 · 가상 회사·가상 인물 데이터")

# ---- 1. 한눈에 ----
emp = db.query("SELECT * FROM employee WHERE leave_date IS NULL")
c1, c2, c3, c4 = st.columns(4)
c1.metric("재직 인원", f"{len(emp)}명")
c2.metric("생산직 (교대)", f"{emp['shift_group'].notna().sum()}명")
c3.metric("관리직", f"{emp['shift_group'].isna().sum()}명")
c4.metric("9월 출퇴근 기록", f"{db.query('SELECT COUNT(*) n FROM attendance')['n'][0]:,}건")

# ---- 2. 처음 보는 분께 ----
with st.container(border=True):
    st.markdown("**5분 둘러보기** — 샘플은 9월 근태 확정과 급여 저장(작성중)까지 된 상태로 시작합니다")
    tour = [
        ("views/s09_work_summary.py", "근태 집계", "'사례별 검증'에서 야간조·휴일 특근·자정 넘는 공휴일 근무가 기본·연장·야간·휴일로 나뉘는 과정"),
        ("views/s11_payroll_calc.py", "급여 계산", "'검증 추천'에서 통상시급 → 주휴 판정 → 항목별 계산식 → 4대보험 → 소득세(간이세액표)"),
        ("views/s12_payroll_ledger.py", "급여대장·마감", "확정 전 점검 → 확정 → '금액 1원 바꿔 보기'로 DB가 수정을 거부하는지"),
        ("views/s13_payslip.py", "임금명세서", "계산 근거가 들어간 명세서 PDF 내려받기"),
        ("views/s14_dashboard.py", "인사 대시보드", "부서별 인건비, 연장근로 상위자, 주 52시간 초과자"),
    ]
    for i, (page, title, what) in enumerate(tour, 1):
        c1, c2 = st.columns([1, 3])
        c1.page_link(page, label=f"{i}. {title}")
        c2.caption(what)
    st.caption("무엇을 눌러도 괜찮습니다. 사이드바의 '샘플 데이터 초기화'로 언제든 처음 상태로 돌아갑니다. "
               "계산 규칙은 법령 원문 대조와 손계산 검증 전입니다.")

# ---- 3. 데이터 흐름 (기획서 §5-1) ----
st.subheader("데이터 흐름")
st.graphviz_chart("""
digraph {
  rankdir=LR; node [shape=box, style="rounded", fontname="sans-serif", fontsize=11];
  A [label="사원 · 임금 이력"]; B [label="근무조"]; C [label="월 근무표"];
  D [label="출퇴근 기록"]; H [label="휴가 사용"]; E [label="근로시간 집계"];
  F [label="연도별 요율표"]; G [label="급여 계산"]; I [label="급여대장 · 임금명세서"];
  J [label="월 마감 (수정 잠금)"];
  A -> C; B -> C; C -> D; D -> E; H -> E; E -> G; A -> G; F -> G; G -> I; I -> J;
}
""")

# ---- 4. 진행 상황 ----
left, right = st.columns(2)

with left:
    st.subheader("화면 14개")
    screens = pd.DataFrame(
        [(s[0], s[1], s[2], s[4], ui.STATUS_TEXT.get(s[5], f"{s[5]} 예정")) for s in ui.SCREENS],
        columns=["ID", "메뉴", "화면", "우선순위", "상태"])
    st.dataframe(screens, hide_index=True, width="stretch", height=530)

with right:
    st.subheader("테이블 17개")
    counts = db.table_counts()
    counts.insert(0, "묶음", counts["table"].map(lambda t: ui.TABLES[t][0]))
    counts.insert(2, "이름", counts["table"].map(lambda t: ui.TABLES[t][1]))
    ui.show(counts, height=530)
