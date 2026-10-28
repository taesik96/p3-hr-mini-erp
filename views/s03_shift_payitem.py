from datetime import datetime, timedelta

import streamlit as st

from erp import db, ui

ui.header("S03")


def hours(start, end):
    """'HH:MM' 두 개 사이 시간. 끝이 더 이르면 다음 날로 본다"""
    s, e = (datetime.strptime(t, "%H:%M") for t in (start, end))
    if e <= s:
        e += timedelta(days=1)
    return (e - s).total_seconds() / 3600


# ---- 1. 근무조 ----
st.subheader("근무조")
shifts = db.query("SELECT * FROM shift")
shifts["휴게(h)"] = [hours(a, b) for a, b in zip(shifts["break_start"], shifts["break_end"])]
shifts["근무(h)"] = [hours(a, b) for a, b in zip(shifts["start_time"], shifts["end_time"])] - shifts["휴게(h)"]
ui.show(shifts)
st.caption("교대 형태는 인터뷰 후 확정합니다 (기획서 §9-1). 지금은 10시간 근무 = 소정 8 + 연장 2로 가정했습니다. "
           "휴게 시작·종료 시각까지 저장하는 이유는 야간근로(22~06시)에서 휴게를 정확히 빼기 위해서입니다 (R4).")

# ---- 2. 급여항목 ----
st.subheader("급여항목")
items = db.query("SELECT item_code, name, kind, taxable, ordinary_wage FROM pay_item ORDER BY sort")
for col in ("taxable", "ordinary_wage"):
    items[col] = items[col].map({1: "예", 0: "아니오"})
ui.show(items)
st.caption("통상임금 포함 여부가 모든 가산수당의 출발점입니다 (R1). 생산직 연장·야간수당 비과세 요건은 확인 전입니다 (기획서 §9-4).")
