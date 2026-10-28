import pandas as pd
import streamlit as st

from erp import incometax, payroll, ui

ui.header("S11")

MONEY = st.column_config.NumberColumn(format="localized")
hm, num = payroll.hm, payroll.num

months = payroll.months_confirmed()
if not months:
    st.info("확정된 근태가 없습니다. 급여는 S09에서 확정한 근로시간으로만 계산합니다. S09에서 '지금 결과로 확정'을 먼저 누르세요.",
            icon=":material/timer:")
    st.stop()
year, month = st.selectbox("귀속연월 (근태를 확정한 달)", months, format_func=lambda ym: f"{ym[0]}년 {ym[1]}월")

try:
    results, when, item_name, item_kind = payroll.calc(year, month)
except ValueError as e:
    st.error(str(e))
    st.stop()
by_emp = {r["emp_no"]: r for r in results}
lines = payroll.lines_frame(results, item_name, item_kind)

# ---- 1. 요약 ----
st.dataframe(pd.DataFrame([{"인원": f"{len(results)}명", "지급 합계": sum(r["pay_total"] for r in results),
                            "공제 합계 (4대보험·소득세)": sum(r["deduct"] for r in results),
                            "실지급": sum(r["net"] for r in results),
                            "지급일": f"{when} (토·일·공휴일이면 앞당김)"}]),
             hide_index=True, width="stretch",
             column_config={c: MONEY for c in ("지급 합계", "공제 합계 (4대보험·소득세)", "실지급")})

with st.expander("계산 전제 — 손계산할 때 같이 보세요", icon=":material/rule:"):
    st.dataframe(pd.DataFrame(payroll.ASSUMPTIONS, columns=["구분", "이렇게 계산했다"]), hide_index=True, width="stretch")

tab1, tab2, tab3 = st.tabs(["사원별 계산 근거", "급여대장 미리보기", "점검"])

# ---- 2. 사원별 계산 근거 ----
with tab1:
    picks = payroll.pick(results)
    labels = {p["id"]: f"{p['id']} {p['title']}" for p in picks}
    chosen = st.pills(f"검증 추천 ({len(picks)}명)", list(labels), format_func=labels.get, default=picks[0]["id"])
    start_emp = next((p["emp_no"] for p in picks if p["id"] == chosen), results[0]["emp_no"])
    names = {r["emp_no"]: f"{r['emp_no']} {r['name']} ({r['dept']} · {r['pay_type']}제)" for r in results}
    emp = st.selectbox("사원 — 추천 밖의 사원도 고를 수 있습니다", list(names), index=list(names).index(start_emp),
                       format_func=names.get, key=f"emp-{chosen}")
    r = by_emp[emp]

    st.markdown("**① 기준 정보**")
    fixed_txt = ", ".join(f"{item_name[k]} {v:,}원" for k, v in r["fixed"].items()) or "없음"
    st.dataframe(pd.DataFrame([{
        "사번": r["emp_no"], "이름": r["name"], "부서": r["dept"], "급여형태": r["pay_type"],
        "주 소정시간": f"{r['weekly_hours']:g}", "입사일": r["hire_date"], "재직일수": f"{r['worked_days']}/{r['n_days']}일",
        "적용 임금 (적용일)": f"{'월 기본급' if r['pay_type'] == '월급' else '시급'} {r['base']:,}원 ({r['wage_eff']})",
        "고정수당": fixed_txt, "공제대상가족 (본인 포함)": f"{r['tax_family']}명",
        "8~20세 자녀": f"{r['tax_children']}명", "원천징수 비율": f"{r['withholding_pct']}%"}]),
        hide_index=True, width="stretch")
    st.caption("공제대상가족·자녀 수·원천징수 비율은 S04 인사카드에서 고칩니다.")

    st.markdown("**② 통상시급 (R1)** — 연장·야간·휴일 수당의 기준")
    ord_fixed = [v for k, v in r["fixed"].items() if k in r["ordinary_codes"]]
    fixed_sum = " + ".join(f"{v:,}" for v in ord_fixed)
    if r["pay_type"] == "월급":
        formula = f"({r['base']:,} + {fixed_sum}) ÷ {r['monthly_hours']:g}" if ord_fixed else f"{r['base']:,} ÷ {r['monthly_hours']:g}"
    else:
        formula = f"{r['base']:,} + ({fixed_sum}) ÷ {r['monthly_hours']:g}" if ord_fixed else f"{r['base']:,}"
    st.markdown(f"`{formula}` = **{num(r['ordinary'])}원**")
    st.caption(f"최저임금 비교용 환산 시급 (R8, 매월 고정 수당 전액 산입): {num(r['min_wage_hourly'])}원")

    st.markdown("**③ 근로시간** — S09에서 확정한 값")
    w = r["work"]
    cols = st.columns(7 if r["pay_type"] == "시급" else 5)
    for col, (k, v) in zip(cols, [("기본", w["기본"]), ("연장", w["연장"]), ("야간", w["야간"]),
                                  ("휴일", w["휴일"]), ("휴일8h초과", w["휴일8h초과"])]):
        col.metric(k, hm(v / 60))
    if r["pay_type"] == "시급":
        cols[5].metric("유급휴가", hm(r["leave_h"]), help="승인된 연차·반차·경조휴가 × 1일 소정근로시간")
        cols[6].metric("유급 공휴일", hm(r["hol_h"]), help="평일에 걸린 공휴일 × 1일 소정근로시간. 주 15시간 미만은 없음")
    if r["absent_days"]:
        st.caption("결근: " + ", ".join(ui.day_label(d) for d in r["absent_days"]))

    st.markdown("**④ 주휴 판정 (R6)** — 일요일이 이 달에 있는 주")
    if r["weeks"]:
        st.dataframe(pd.DataFrame([{k: v for k, v in wk.items() if k != "결근일"} | {"개근": "개근" if wk["개근"] else "✗"}
                                   for wk in r["weeks"]]), hide_index=True, width="stretch")
    st.caption("월급제는 주휴수당이 월급에 들어 있어 따로 주지 않고, 결근한 주만 기본급 공제에 씁니다."
               if r["pay_type"] == "월급" else "개근한 주마다 주휴수당이 나옵니다. 유급휴가는 출근으로 봅니다.")

    st.markdown("**⑤ 급여 항목과 계산 근거**")
    mine = lines[lines["사번"] == emp][["구분", "항목", "금액", "계산 근거"]]
    st.dataframe(mine, hide_index=True, width="stretch", column_config={"금액": MONEY})
    meal = r["pay_total"] - r["taxable"]
    st.dataframe(pd.DataFrame([
        {"합계": "지급 합계", "금액": r["pay_total"], "설명": "지급 항목을 모두 더한 값"},
        {"합계": "비과세", "금액": meal, "설명": "식대 중 월 20만 원까지"},
        {"합계": "과세 급여", "금액": r["taxable"], "설명": "지급 합계 − 비과세 → 4대보험 보수월액(단순화)·간이세액표 월급여액"},
        {"합계": "공제 합계", "금액": r["deduct"], "설명": "4대보험 + 소득세 + 지방소득세"},
        {"합계": "실지급", "금액": r["net"], "설명": "지급 합계 − 공제 합계"}]),
        hide_index=True, width="stretch", column_config={"금액": MONEY})
    for level, text in r["notes"]:
        (st.error if level == "오류" else st.warning)(text)

    st.markdown("**⑥ 소득세 (R9)** — 근로소득 간이세액표에서 찾은 줄")
    row = incometax.row_for(r["taxable"])
    if row is None:
        st.caption(f"과세 급여 {r['taxable']:,}원은 표의 최저 구간(770천원)보다 적어 소득세가 없습니다.")
    else:
        pick_col = f"{min(r['tax_family'], 11)}명"
        st.dataframe(row.style.map(lambda _: "background-color: #fff4cc; font-weight: 700", subset=[pick_col]),
                     hide_index=True, width="stretch",
                     column_config={c: MONEY for c in row.columns if c.endswith("명")})
        st.caption(f"표의 가로는 공제대상가족 수(본인·배우자 포함)입니다. 이 사원은 {r['tax_family']}명이라 노란 칸을 씁니다. "
                   "그다음 8~20세 자녀 공제를 빼고 원천징수 비율을 곱합니다. 표: 소득세법 시행령 별표 2 (2026.2.27 개정, "
                   "3/1 지급분부터) — 민간 사본 PDF에서 옮겨 홈택스 원본 대조가 필요합니다.")

    with st.expander("내 손계산과 맞춰 보기"):
        st.caption("손으로 계산한 금액(원)을 넣으면 비교합니다. 저장되지 않으니 엑셀 손계산표에도 적어 두세요.")
        targets = [(code, amount) for code, amount, _ in r["lines"]]
        cols = st.columns(4)
        mine_calc = {code: cols[i % 4].number_input(item_name[code], min_value=0, step=1, key=f"{emp}-{code}")
                     for i, (code, _) in enumerate(targets)}
        entered = {code: v for code, v in mine_calc.items() if v}
        if not entered:
            st.caption("아직 입력 전입니다.")
        else:
            diff = [(code, v, amount) for code, amount in targets if (v := mine_calc[code]) and v != amount]
            if diff:
                st.warning("다른 항목: " + ", ".join(f"{item_name[c]} (내 계산 {v:,} / 시스템 {a:,})" for c, v, a in diff))
            else:
                st.success(f"입력한 {len(entered)}개 항목이 모두 일치합니다.")

    st.download_button("전 직원 항목·계산 근거 내려받기 (CSV)", lines.to_csv(index=False).encode("utf-8-sig"),
                       f"급여계산근거_{year}-{month:02d}.csv", "text/csv", icon=":material/download:")

# ---- 3. 급여대장 미리보기 ----
with tab2:
    ledger = payroll.ledger_table(lines)
    st.dataframe(ledger, hide_index=True, width="stretch",
                 column_config={c: MONEY for c in ledger.columns if c not in ("사번", "이름", "부서")})
    st.caption("저장 전 미리 보기입니다. 확정과 마감은 S12에서 합니다.")
    st.download_button("급여대장 내려받기 (CSV)", ledger.to_csv(index=False).encode("utf-8-sig"),
                       f"급여대장_{year}-{month:02d}.csv", "text/csv", icon=":material/download:")

# ---- 4. 점검 ----
with tab3:
    checks = [{"사번": r["emp_no"], "이름": r["name"], "구분": level, "내용": text} for r in results for level, text in r["notes"]]
    checks += [{"사번": r["emp_no"], "이름": r["name"], "구분": "확인",
                "내용": "결근 " + ", ".join(ui.day_label(d) for d in r["absent_days"])} for r in results if r["absent_days"]]
    checks += [{"사번": r["emp_no"], "이름": r["name"], "구분": "확인",
                "내용": "4대보험 " + ("적용 제외 (월 소정 60시간 미만)" if not r["covered"] else "국민연금·건강 취득월 제외 (월 중 입사)")}
               for r in results if not r["covered"] or r["mid_month"]]
    st.dataframe(pd.DataFrame(checks), hide_index=True, width="stretch")

# ---- 5. 저장 ----
st.divider()
run = payroll.saved_run(year, month)
left, right = st.columns([3, 1])
if run is not None and run["status"] == "확정":
    left.markdown(f"**{year}년 {month}월 급여**  \n확정된 회차입니다 ({run['closed_at']}). 다시 계산할 수 없습니다.")
else:
    left.markdown(f"**{year}년 {month}월 급여 저장**  \n"
                  + (f"작성중 회차가 있습니다 (지급일 {run['pay_date']}). 다시 저장하면 지금 결과로 바뀝니다."
                     if run is not None else "저장하면 급여 회차(작성중)와 항목별 금액·계산 근거가 DB에 남고, S12에서 확정할 수 있습니다."))
    if right.button("계산 결과 저장", type="primary", icon=":material/save:", width="stretch"):
        run_id = payroll.save(year, month, results, when)
        st.toast(f"{len(lines)}줄을 저장했습니다 (회차 {run_id}, 작성중)", icon=":material/save:")
        st.rerun()
