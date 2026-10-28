# =========================================================
#  다온정밀(가상) HR 미니 ERP — 인사·근태·급여 (P3)
#  기획서: docs/01_기획서_v0.1.md
# =========================================================

import streamlit as st

from erp import db, ui

# ---- 1. 화면 기본 설정 ----
st.set_page_config(page_title="다온정밀 HR 미니 ERP", page_icon="🏭", layout="wide")

# ---- 2. DB가 없으면 샘플 데이터로 새로 만든다 ----
db.ensure()

# ---- 3. 메뉴: 기획서 §6 화면 목록 그대로 ----
pages = {"": [st.Page("views/home.py", title="홈", icon=":material/home:", default=True)]}
for sid, menu, title, file, prio, status, icon, _ in ui.SCREENS:
    pages.setdefault(menu, []).append(
        st.Page(f"views/{file}", title=f"{sid} {title}", icon=icon, url_path=sid.lower()))
nav = st.navigation(pages, expanded=True)       # 화면 15개를 접지 않고 다 보여준다

# ---- 4. 사이드바 아래쪽: 안내 + 초기화 ----
with st.sidebar:
    st.caption("⚠️ 가상 회사·가상 인물 데이터입니다. 계산 규칙은 법령 원문 대조와 손계산 검증 전입니다.")
    if st.button("샘플 데이터 초기화", icon=":material/restart_alt:", width="stretch"):
        db.build(reset=True, demo=True)
        st.rerun()

nav.run()
