import pandas as pd
import streamlit as st

from erp import payroll, payslip, ui

ui.header("S13")

MONEY = st.column_config.NumberColumn(format="localized")

runs = payroll.runs()
if runs.empty:
    st.info("저장된 급여 회차가 없습니다. S11에서 '계산 결과 저장'을 먼저 누르세요.", icon=":material/calculate:")
    st.stop()

label = {r.run_id: f"{r.pay_month} {r.run_kind} · {r.status}" for r in runs.itertuples()}
c1, c2 = st.columns(2)
run_id = c1.selectbox("급여 회차", list(label), format_func=label.get)
people = payroll.saved_lines(run_id).drop_duplicates("사번")
names = {r.사번: f"{r.사번} {r.이름} ({r.부서})" for r in people.itertuples()}
emp = c2.selectbox("사원", list(names), format_func=names.get)
d = payslip.data(run_id, emp)

if d["status"] != "확정":
    st.warning("확정 전(작성중) 회차입니다. 명세서와 PDF에 '확정 전' 표시가 붙습니다. 확정은 S12에서 합니다.",
               icon=":material/edit_note:")

# ---- 1. 화면 명세서 ----
with st.container(border=True):
    st.markdown(f"### 임금명세서\n{d['company']} · 귀속 {d['year']}년 {d['month']}월 · 지급일 **{d['pay_date']}**")
    st.dataframe(pd.DataFrame([{"성명": d["name"], "사번": d["emp_no"], "부서": d["dept"],
                                "직급": f"{d['rank']} ({d['pay_type']}제)"}]), hide_index=True, width="stretch")

    st.markdown("**근로시간** (근태 확정값)")
    st.dataframe(pd.DataFrame([d["hours"]]), hide_index=True, width="stretch")

    for title, rows, total_label, total in [("지급 내역", d["pay"], "지급 총액", d["pay_total"]),
                                            ("공제 내역", d["deduct"], "공제 총액", d["deduct_total"])]:
        st.markdown(f"**{title}**")
        table = pd.DataFrame([(item, f"{amount:,}", basis) for item, amount, basis in rows + [(total_label, total, "")]],
                             columns=["항목", "금액(원)", "계산 방법"])
        st.table(table.set_index("항목"))          # 계산 방법이 길어도 잘리지 않게 줄바꿈되는 정적 표

    st.metric("실지급액", f"{d['net']:,}원", help="지급 총액 − 공제 총액")

# ---- 2. 내려받기 ----
if payslip.font() is None:
    st.error("한글 글꼴(맑은 고딕 또는 나눔고딕)을 찾지 못해 PDF를 만들 수 없습니다.")
else:
    tag = "확정" if d["status"] == "확정" else "확정전"
    month_tag = f"{d['year']}-{d['month']:02d}"
    c1, c2 = st.columns(2)
    c1.download_button("이 사원 명세서 PDF", payslip.pdf_bytes(run_id, [emp]),
                       f"임금명세서_{month_tag}_{emp}_{tag}.pdf", "application/pdf",
                       icon=":material/picture_as_pdf:", width="stretch")
    if c2.button(f"전 직원 {len(names)}명 PDF 만들기", icon=":material/library_books:", width="stretch"):
        st.session_state["all_pdf"] = (run_id, payslip.pdf_bytes(run_id, list(names)))
    made = st.session_state.get("all_pdf")
    if made and made[0] == run_id:
        c2.download_button("전 직원 명세서 PDF 내려받기 (1명당 1장)", made[1], f"임금명세서_{month_tag}_전직원_{tag}.pdf",
                           "application/pdf", icon=":material/download:", width="stretch")

# ---- 3. 법정 기재사항 점검 (R10) ----
with st.expander("법정 기재사항 점검 (R10) — 근로기준법 제48조 제2항, 시행령 제27조의2 [원문 확인 필요]",
                 icon=":material/checklist:"):
    st.dataframe(pd.DataFrame([{"기재사항": need, "이 명세서에서": where, "들어감": "✓"} for need, where in payslip.REQUIRED]),
                 hide_index=True, width="stretch")
    st.caption("근로시간에 따라 금액이 달라지는 항목(기본급·연장·야간·휴일·주휴)은 계산 방법 칸에 시간 수와 계산식이 함께 들어갑니다. "
               "S11이 저장한 계산 근거를 그대로 옮긴 것입니다.")
