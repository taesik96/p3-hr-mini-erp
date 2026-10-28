import streamlit as st

from erp import db, ui

ui.header("S05")

hist = db.query("""
    SELECT a.eff_date, a.emp_no, e.name, c.name AS kind, a.before_value, a.after_value
      FROM assignment a
      JOIN employee e USING (emp_no)
      JOIN code c ON c.grp = '발령종류' AND c.code = a.kind
     ORDER BY a.eff_date DESC, a.emp_no""")

kinds = st.multiselect("발령 구분", list(dict.fromkeys(hist["kind"])), placeholder="전체")
if kinds:
    hist = hist[hist["kind"].isin(kinds)]

st.caption(f"{len(hist)}건 · 최근 순")
ui.show(hist)
st.caption("발령 등록 입력 화면은 이후에 붙입니다 (☆). 지금은 샘플 이력만 조회합니다.")
