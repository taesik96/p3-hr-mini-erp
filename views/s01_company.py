import streamlit as st

from erp import db, ui

ui.header("S01")

# ---- 1. 회사 설정 ----
c = db.query("SELECT * FROM company").iloc[0]
c1, c2, c3, c4 = st.columns(4)
c1.metric("회사", c["name"])
c2.metric("상시근로자 수", f"{c['regular_headcount']}명",
          help="5인 이상이면 근로기준법 전면 적용, 5인 미만이면 가산수당·연차 등 일부 미적용 (R11)")
c3.metric("월 소정근로시간", f"{c['monthly_hours']:.0f}시간", help="월급 → 통상시급 환산에 쓴다 (R1)")
c4.metric("연차 기준", c["leave_basis"], help="입사일 vs 회계연도 — 인터뷰 후 확정 (기획서 §9-2)")
st.caption(f"급여 지급일: 다음 달 {c['pay_day']}일 · 주 소정근로시간 {c['weekly_hours']:.0f}시간 · 업종: {c['industry']}")

# ---- 2. 연도별 요율표 ----
st.subheader("연도별 요율표")
rates = db.query("SELECT * FROM rate_table")
if (rates["verified"] == 0).any():
    st.warning("공식 고시 원문과 대조하기 전 값입니다. 급여 계산(3주차) 전에 확인해야 합니다.", icon=":material/warning:")
rates["verified"] = rates["verified"].map({1: "완료", 0: "대조 전"})
ui.show(rates)

# ---- 3. 공휴일 달력 ----
st.subheader("공휴일 달력")
ui.show(db.query("SELECT * FROM holiday ORDER BY date"))
st.caption("2026년 9~12월 공휴일이 들어 있습니다. 같은 근무라도 공휴일이면 휴일근로가 되고, "
           "S07이 근무표를 만들 때 이 달력을 씁니다 (R3).")
