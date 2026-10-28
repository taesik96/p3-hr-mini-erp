import streamlit as st

from erp import db, ui

ui.header("S10")
st.badge("R7 연차 발생 — 원문 대조·손계산 전", icon=":material/rule:", color="gray")

emp = db.employees()
emp = emp[emp["leave_date"].isna()]
grants = db.query("SELECT * FROM leave_grant ORDER BY emp_no, grant_date")
uses = db.query("""
    SELECT l.id, l.emp_no, l.use_date, c.name AS leave_type, l.days, l.status
      FROM leave_use l JOIN code c ON c.grp = '휴가종류' AND c.code = l.leave_type
     ORDER BY l.use_date""")

# ---- 1. 사원별 잔여 = 발생 − 사용(승인된 연차·반차만) ----
granted = grants.groupby("emp_no")["days"].sum().rename("발생")
used = (uses[(uses["status"] == "승인") & uses["leave_type"].isin(["연차", "반차"])]
        .groupby("emp_no")["days"].sum().rename("사용"))
summary = emp[["emp_no", "name", "dept", "hire_date", "weekly_hours"]].set_index("emp_no").join([granted, used]).fillna(0)
summary["잔여"] = summary["발생"] - summary["사용"]

pending = uses[uses["status"] == "신청"]
c1, c2, c3 = st.columns(3)
c1.metric("9월 승인된 연차·반차", f"{used.sum():g}일")
c2.metric("승인 대기", f"{len(pending)}건")
c3.metric("연차 없음 (주 15시간 미만·입사 1개월 미만)", f"{(summary['발생'] == 0).sum()}명")

tab1, tab2, tab3 = st.tabs(["사원별 잔여", "발생 내역", "사용·신청 내역"])
with tab1:
    ui.show(summary.reset_index())
with tab2:
    ui.show(grants.merge(emp[["emp_no", "name"]], on="emp_no").drop(columns="id"))
    st.caption("입사일 기준. 1년 미만은 1개월 개근마다 1일, 1년 이상은 15일에 3년차부터 2년마다 1일 가산 (최대 25일). "
               "이미 소멸된 발생분은 넣지 않았습니다.")
with tab3:
    ui.show(uses.merge(emp[["emp_no", "name"]], on="emp_no").drop(columns="id"))
    st.caption("경조휴가는 회사가 따로 주는 휴가라 연차에서 빼지 않습니다. 신청·승인 처리 버튼은 이후에 붙입니다.")
