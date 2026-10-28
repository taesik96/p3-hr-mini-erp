import json

import streamlit as st

from erp import db, rules, ui

ui.header("S06")

AS_OF = "2026-09-30"

# ---- 1. 임금 이력 전체 + 고정수당 펼치기 ----
wages = db.query("""
    SELECT w.emp_no, e.name, e.pay_type, w.eff_date, w.base_amount, w.fixed_items, e.leave_date
      FROM wage_contract w JOIN employee e USING (emp_no)
     ORDER BY w.emp_no, w.eff_date""")
fixed = wages["fixed_items"].map(json.loads)
wages["직책수당"] = fixed.map(lambda f: f.get("P02", 0))
wages["식대"] = fixed.map(lambda f: f.get("P03", 0))
wages = wages.drop(columns="fixed_items")

# ---- 2. 기준일에 적용되는 임금 = 적용일이 기준일 이전인 것 중 가장 최근 ----
employed = wages["leave_date"].isna() | (wages["leave_date"] >= AS_OF)
current = (wages[employed & (wages["eff_date"] <= AS_OF)]
           .sort_values("eff_date").groupby("emp_no").tail(1).sort_values("emp_no"))
wages, current = wages.drop(columns="leave_date"), current.drop(columns="leave_date")

# ---- 3. 최저임금 (R8) — 매월 고정 지급하는 수당까지 넣은 환산 시급으로 비교 ----
company = db.query("SELECT monthly_hours FROM company").iloc[0]
min_wage = int(db.query("SELECT min_wage FROM rate_table WHERE year = 2026")["min_wage"][0])
current["최저임금 환산 시급"] = [
    round(float(rules.min_wage_hourly(t, b, {"P02": a, "P03": m}, company["monthly_hours"])), 2)
    for t, b, a, m in zip(current["pay_type"], current["base_amount"], current["직책수당"], current["식대"])]
below = current[current["최저임금 환산 시급"] < min_wage]
base_only = current[(current["pay_type"] == "시급") & (current["base_amount"] < min_wage)
                    & (current["최저임금 환산 시급"] >= min_wage)]

tab1, tab2 = st.tabs([f"{AS_OF} 기준 적용 임금", "전체 이력"])
with tab1:
    if len(below):
        st.error(f"{len(below)}명이 2026년 최저시급({min_wage:,}원)보다 낮습니다 (R8).", icon=":material/error:")
        ui.show(below)
    if len(base_only):
        st.warning(f"시급제 {len(base_only)}명은 시급만 보면 {min_wage:,}원보다 낮지만, 매월 고정 지급하는 수당(식대 등)을 넣은 "
                   "환산 시급으로는 충족합니다. 최저임금 산입범위 기준이며 [원문 확인 필요], 2026년 임금 갱신이 빠진 건 아닌지 확인하세요.",
                   icon=":material/warning:")
        ui.show(base_only)
    ui.show(current)
    st.caption("최저임금 환산 시급 = 월급제 (기본급 + 고정수당) ÷ 209, 시급제 시급 + 고정수당 ÷ 209. "
               "매월 정기 지급하는 수당·복리후생비는 2024년부터 전액 산입합니다 (최저임금법 제6조 제4항) [원문 확인 필요].")
with tab2:
    ui.show(wages)
st.caption("임금이 바뀌면 덮어쓰지 않고 적용일이 다른 새 줄을 추가합니다. 샘플은 2025년 이력부터 넣었습니다.")
