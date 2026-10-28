import json

import pandas as pd
import streamlit as st

from erp import db, incometax, ui

ui.header("S04")

emp = db.employees()

# ---- 1. 조회 조건 ----
c1, c2 = st.columns([3, 1])
depts = c1.multiselect("부서", sorted(emp["dept"].unique()), placeholder="전체 부서")
state = c2.radio("재직 상태", ["재직", "퇴사", "전체"], horizontal=True)

view = emp
if depts:
    view = view[view["dept"].isin(depts)]
if state == "재직":
    view = view[view["leave_date"].isna()]
elif state == "퇴사":
    view = view[view["leave_date"].notna()]

st.caption(f"{len(view)}명")
ui.show(view)

# ---- 2. 인사카드: 현재 값 + 이력 ----
st.subheader("인사카드")
label = {r.emp_no: f"{r.emp_no} {r.name} ({r.dept} {r.rank})" for r in emp.itertuples()}
pick = st.selectbox("사원 선택", list(label), format_func=label.get)
p = emp[emp["emp_no"] == pick].iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("부서 / 직급", f"{p['dept']} / {p['rank']}")
c2.metric("고용형태", f"{p['emp_type']} · {p['pay_type']}")
c3.metric("입사일", p["hire_date"])
c4.metric("교대 조", p["shift_group"] if pd.notna(p["shift_group"]) else "-")

left, right = st.columns(2)
with left:
    st.markdown("**발령 이력**")
    ui.show(db.query("""
        SELECT a.eff_date, c.name AS kind, a.before_value, a.after_value
          FROM assignment a JOIN code c ON c.grp = '발령종류' AND c.code = a.kind
         WHERE a.emp_no = ? ORDER BY a.eff_date""", (pick,)))
with right:
    st.markdown("**임금 이력**")
    wages = db.query("SELECT eff_date, base_amount, fixed_items FROM wage_contract WHERE emp_no = ? ORDER BY eff_date",
                     (pick,))
    wages["fixed_items"] = wages["fixed_items"].map(
        lambda s: ", ".join(f"{k} {v:,}원" for k, v in json.loads(s).items()) or "-")
    ui.show(wages.rename(columns={"fixed_items": "고정수당"}))
st.caption("현재 값은 사원 테이블에, 바뀐 내역은 발령·임금 이력에 쌓습니다. 덮어쓰지 않아야 지난달 급여를 다시 계산할 수 있습니다.")

# ---- 3. 원천징수 정보 (R9 소득세) ----
st.markdown("**원천징수 정보** — 소득세(간이세액표)에 씁니다")
with st.form(f"tax-{pick}"):
    c1, c2, c3 = st.columns(3)
    family = c1.number_input("공제대상가족 수 (본인·배우자 포함)", 1, 20, int(p["tax_family"]),
                             help="본인과 배우자도 각각 1명으로 셉니다 (소득세법 시행령 별표 2 제2호)")
    children = c2.number_input("그중 8세 이상 20세 이하 자녀 수", 0, 19, int(p["tax_children"]),
                               help="자녀 1명 20,830원, 2명 45,830원, 3명부터 1명당 33,330원 더해 세액에서 뺍니다")
    pct = c3.selectbox("원천징수 비율", incometax.PCT, index=incometax.PCT.index(int(p["withholding_pct"])),
                       format_func=lambda v: f"{v}%", help="근로자가 80·100·120% 중 고릅니다 [원문 확인 필요]")
    if st.form_submit_button("저장", icon=":material/save:"):
        try:
            incometax.set_profile(pick, family, children, pct)
            st.toast(f"{pick} 원천징수 정보를 저장했습니다", icon=":material/save:")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
st.caption("실무에서는 근로자가 '근로소득 원천징수 신고서'로 내는 정보입니다. 샘플 값은 가상입니다. "
           "작성중인 급여에는 S11에서 다시 저장해야 반영되고, S12 확정 전 점검이 바뀐 값을 잡아냅니다.")
