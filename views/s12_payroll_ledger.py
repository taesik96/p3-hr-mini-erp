import pandas as pd
import streamlit as st

from erp import payroll, ui

ui.header("S12")

MONEY = st.column_config.NumberColumn(format="localized")

runs = payroll.runs()
if runs.empty:
    st.info("저장된 급여 회차가 없습니다. S11에서 '계산 결과 저장'을 먼저 누르세요.", icon=":material/calculate:")
    st.stop()

label = {r.run_id: f"{r.pay_month} {r.run_kind} · {r.status} · 지급일 {r.pay_date}" for r in runs.itertuples()}
run_id = st.selectbox("급여 회차", list(label), format_func=label.get)
run = runs[runs["run_id"] == run_id].iloc[0]
year, month = int(run["pay_month"][:4]), int(run["pay_month"][5:])
closed = run["status"] == "확정"

lines = payroll.saved_lines(run_id)
ledger = payroll.ledger_table(lines)
total = ledger.iloc[-1]

# ---- 1. 요약 ----
if closed:
    st.badge(f"확정 {run['closed_at']}", icon=":material/lock:", color="green")
else:
    st.badge("작성중 — 확정 전", icon=":material/edit_note:", color="orange")
st.dataframe(pd.DataFrame([{"인원": f"{len(ledger) - 1}명", "지급 총액": int(total["지급 합계"]),
                            "공제 총액": int(total["공제 합계"]), "실지급 총액": int(total["실지급"])}]),
             hide_index=True, width="stretch",
             column_config={c: MONEY for c in ("지급 총액", "공제 총액", "실지급 총액")})

# ---- 2. 급여대장 ----
tab1, tab2, tab3 = st.tabs(["급여대장", "부서별 합계", "항목별 합계"])
with tab1:
    st.dataframe(ledger, hide_index=True, width="stretch",
                 column_config={c: MONEY for c in ledger.columns if c not in ("사번", "이름", "부서")})
with tab2:
    body = ledger.iloc[:-1]
    by_dept = body.groupby("부서")[["지급 합계", "공제 합계", "실지급"]].sum()
    by_dept.insert(0, "인원", body.groupby("부서").size())
    st.dataframe(by_dept.reset_index(), hide_index=True, width="stretch",
                 column_config={c: MONEY for c in ("지급 합계", "공제 합계", "실지급")})
with tab3:
    by_item = (lines.groupby(["구분", "항목코드", "항목"])["금액"]
               .agg(합계="sum", 받는_인원=lambda s: int((s != 0).sum())).reset_index()
               .rename(columns={"받는_인원": "0원 아닌 인원"}))
    st.dataframe(by_item.drop(columns="항목코드"), hide_index=True, width="stretch", column_config={"합계": MONEY})

st.download_button("급여대장 엑셀 내려받기 (급여대장 + 계산 근거 2개 시트)",
                   payroll.ledger_xlsx(ledger, lines, f"(가상) 다온정밀 {year}년 {month}월 급여대장 · {run['status']}"),
                   f"급여대장_{run['pay_month']}_{run['status']}.xlsx", icon=":material/download:")

# ---- 3. 확정 (마감) ----
st.divider()
if not closed:
    st.subheader("확정 전 점검")
    check = payroll.review(run, year, month)
    blocked = False
    if check["diff"] is None or check["errors"]:
        blocked = True
        for e in check["errors"]:
            st.error(e)
    elif len(check["diff"]):
        blocked = True
        st.error(f"저장한 뒤 바뀐 값이 {len(check['diff'])}건 있습니다. 근태 재확정, 임금 변경, 원천징수 정보(부양가족) 변경 때문일 수 있습니다. "
                 "S11에서 다시 저장한 뒤 확정하세요.", icon=":material/sync_problem:")
        st.dataframe(check["diff"], hide_index=True, width="stretch")
    else:
        st.success("저장한 값이 지금 계산과 같고, 최저임금 미달도 없습니다.", icon=":material/task_alt:")

    if st.button("급여 확정 (마감)", type="primary", icon=":material/lock:", disabled=blocked):
        payroll.confirm(run_id)
        st.toast(f"{run['pay_month']} 급여를 확정했습니다", icon=":material/lock:")
        st.rerun()
    st.caption("확정하면 급여 상세의 추가·수정·삭제를 DB 트리거가 직접 막고, S11에서도 다시 저장할 수 없습니다. "
               "임금명세서(S13)는 확정 전에도 볼 수 있지만 '확정 전' 표시가 붙습니다.")
else:
    st.success(f"{run['closed_at']}에 확정됐습니다. 급여 상세는 수정할 수 없습니다.", icon=":material/lock:")
    left, right = st.columns(2)
    with left:
        st.markdown("**잠금 시험**")
        st.caption("확정된 회차의 금액을 1원 바꿔 보는 버튼입니다. DB가 거부해야 정상입니다.")
        if st.button("금액 1원 바꿔 보기", icon=":material/science:"):
            msg = payroll.try_edit(run_id)
            if msg:
                st.success(f"DB가 거부했습니다: {msg}")
            else:
                st.error("수정이 들어갔습니다. 잠금 트리거를 확인하세요.")
    with right:
        st.markdown("**확정 취소**")
        st.caption("계산을 고쳐야 할 때만 씁니다. 실무에서는 권한과 취소 사유 기록이 필요합니다 (이번 범위 밖).")
        sure = st.checkbox("확정을 취소하고 작성중으로 되돌립니다")
        if st.button("확정 취소", icon=":material/lock_open:", disabled=not sure):
            payroll.reopen(run_id)
            st.toast("작성중으로 되돌렸습니다", icon=":material/lock_open:")
            st.rerun()
