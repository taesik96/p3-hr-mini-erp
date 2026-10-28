import streamlit as st

from erp import db, ui

ui.header("S02")

left, right = st.columns(2)

# ---- 1. 부서 (상위 부서로 조직도를 만든다) ----
with left:
    st.subheader("부서")
    ui.show(db.query("""
        SELECT d.dept_code, d.name, p.name AS parent, d.job_family,
               (SELECT COUNT(*) FROM employee e
                 WHERE e.dept_code = d.dept_code AND e.leave_date IS NULL) AS 재직
          FROM department d LEFT JOIN department p ON p.dept_code = d.parent_code
         ORDER BY d.dept_code"""))

# ---- 2. 공통코드 (그룹별 탭) ----
with right:
    st.subheader("공통코드")
    codes = db.query("SELECT * FROM code ORDER BY grp, sort")
    groups = list(dict.fromkeys(codes["grp"]))
    for tab, g in zip(st.tabs(groups), groups):
        with tab:
            ui.show(codes[codes["grp"] == g][["code", "name", "sort"]])
