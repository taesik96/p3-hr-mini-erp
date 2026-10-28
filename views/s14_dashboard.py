from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from erp import dashboard, ui

ui.header("S14")

# ---- 색: 범주는 정해진 순서로만 쓰고(돌려 쓰지 않음), 상태색(초과)은 아이콘·글자와 같이 쓴다 ----
DARK = st.context.theme.type == "dark"
SERIES = (["#3987e5", "#d95926", "#199e70", "#c98500"] if DARK
          else ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"])          # 파랑·주황·청록·노랑 (검증한 순서)
BLUE, CRITICAL, MUTED = SERIES[0], "#d03b3b", ("#8a8984" if DARK else "#8f8e89")
MONEY = st.column_config.NumberColumn(format="localized")


def won_short(x):
    """156,987,138 → '1억 5,699만원'"""
    eok, man = divmod(int(round(x / 10_000)), 10_000)
    return f"{eok}억 {man:,}만원" if eok else f"{man:,}만원"


def chart(c, height):
    """height: 숫자(px) 또는 alt.Step(n) — 세로축이 범주면 막대 하나당 높이로 줘야 이름이 가려지지 않는다"""
    st.altair_chart(c.properties(height=height)
                    .configure_axis(grid=True, gridOpacity=0.35, domain=False, labelLimit=160)
                    .configure_view(stroke=None), width="stretch")


run = dashboard.latest_run()
if run is None:
    st.info("저장된 급여가 없습니다. S09에서 근태를 확정하고 S11에서 급여를 저장하면 대시보드가 채워집니다.",
            icon=":material/calculate:")
    st.stop()
year, month = int(run["pay_month"][:4]), int(run["pay_month"][5:])
st.caption(f"{year}년 {month}월 · 급여 {run['status']} 회차 기준 · 근로시간은 S09 확정값 · 다시 계산하지 않고 저장된 값만 모읍니다")

cost = dashboard.labor_cost(run["run_id"])
work = dashboard.work_by_employee(year, month)
weeks = dashboard.weekly_totals(year, month)
over = weeks[weeks["52시간 초과"] > 0]
paid = dashboard.headcount_paid(run["run_id"])
total = cost["금액"].sum()

# ---- 1. 핵심 숫자 ----
r1 = st.columns(3)
r1[0].metric("급여 받은 인원", f"{paid}명")
r1[1].metric("인건비 총액 (지급)", won_short(total), help=f"{total:,}원 · 4대보험 회사 부담분은 빠져 있습니다")
r1[2].metric("1인당 평균", won_short(total / paid), help=f"{total / paid:,.0f}원")
r2 = st.columns(3)
extra = cost[cost["구분"] == "가산수당"]["금액"].sum()
r2[0].metric("가산수당 비중", f"{extra / total:.1%}", help=f"연장·야간·휴일 수당 {extra:,}원")
r2[1].metric("연장+휴일 근로 합계", f"{work['연장+휴일'].sum():,.0f}시간")
r2[2].metric("⚠ 주 52시간 초과", f"{over['emp_no'].nunique()}명 · {len(over)}건",
             help="휴일근로까지 더한 1주(월~일) 총근로가 52시간을 넘은 경우 (R5)")

# ---- 2. 부서별 인건비 구성 ----
st.subheader("부서별 인건비 구성")
order = cost.groupby("부서")["금액"].sum().sort_values(ascending=False).index.tolist()
cost["금액(만원)"] = cost["금액"] / 10_000
cost["순서"] = cost["구분"].map(dashboard.COST_ORDER.index)
bars = alt.Chart(cost).mark_bar(stroke="white" if not DARK else "#1a1a19", strokeWidth=2).encode(
    y=alt.Y("부서:N", sort=order, title=None),
    x=alt.X("sum(금액(만원)):Q", title="만원", stack="zero"),
    color=alt.Color("구분:N", scale=alt.Scale(domain=dashboard.COST_ORDER, range=SERIES),
                    legend=alt.Legend(title=None, orient="top")),
    order=alt.Order("순서:Q"),
    tooltip=["부서", "구분", alt.Tooltip("금액:Q", format=",", title="금액(원)")])
chart(bars, alt.Step(34))
with st.expander("표로 보기"):
    table = cost.pivot_table(index="부서", columns="구분", values="금액", aggfunc="sum", fill_value=0)[
        [c for c in dashboard.COST_ORDER if c in set(cost["구분"])]]
    table["합계"] = table.sum(axis=1)
    st.dataframe(table.loc[order].reset_index(), hide_index=True, width="stretch",
                 column_config={c: MONEY for c in table.columns})
st.caption("기본급 = 시급제는 근로·유급휴가·유급 공휴일 시간분 · 고정수당 = 직책수당·식대 · 가산수당 = 연장·야간·휴일 · 주휴수당 = 시급제만")

# ---- 3. 연장근로 상위 10명 ----
left, right = st.columns(2)
with left:
    st.subheader("연장+휴일 근로 상위 10명")
    top = work.head(10).copy()
    top["사원"] = top["name"] + " (" + top["부서"] + ")"
    ot = alt.Chart(top).mark_bar(color=BLUE, cornerRadiusEnd=4).encode(
        y=alt.Y("사원:N", sort="-x", title=None),
        x=alt.X("연장+휴일:Q", title="시간"),
        tooltip=["emp_no", "name", "부서", alt.Tooltip("연장:Q", format=".2f"), alt.Tooltip("휴일:Q", format=".2f"),
                 alt.Tooltip("야간:Q", format=".2f", title="야간(겹침 포함)")])
    chart(ot, alt.Step(28))

# ---- 4. 주 52시간 ----
with right:
    st.subheader("주별 총근로 분포")
    weeks["상태"] = weeks["52시간 초과"].map(lambda v: "⚠ 52시간 초과" if v > 0 else "52시간 이내")
    dots = alt.Chart(weeks).mark_circle(size=70, opacity=0.8, stroke="white" if not DARK else "#1a1a19",
                                        strokeWidth=2).encode(
        x=alt.X("총근로:Q", title="1주 총근로 (시간)", scale=alt.Scale(zero=False)),
        y=alt.Y("주 표시:N", title=None, sort=sorted(weeks["주 표시"].unique())),
        color=alt.Color("상태:N", scale=alt.Scale(domain=["52시간 이내", "⚠ 52시간 초과"], range=[BLUE, CRITICAL]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=["emp_no", "name", "부서", "주 표시", alt.Tooltip("총근로:Q", format=".2f"), "상태"])
    limit = alt.Chart(pd.DataFrame({"x": [52]})).mark_rule(color=MUTED, strokeDash=[4, 4], strokeWidth=2).encode(x="x:Q")
    chart(dots + limit, alt.Step(56))
    st.caption("점 하나 = 사원 한 명의 한 주. 점선이 주 52시간. 9월 첫 주·마지막 주는 9월 밖 날짜가 비어 덜 잡힙니다.")

if len(over):
    st.markdown("**⚠ 주 52시간 초과 목록**")
    show = over.sort_values("총근로", ascending=False)[["emp_no", "name", "부서", "주 표시", "총근로", "52시간 초과"]]
    st.dataframe(show.rename(columns={"emp_no": "사번", "name": "이름", "주 표시": "주"}), hide_index=True,
                 width="stretch", column_config={"총근로": st.column_config.NumberColumn(format="%.2f"),
                                                 "52시간 초과": st.column_config.NumberColumn(format="+%.2f")})

# ---- 5. 인원 현황 ----
st.subheader("인원 현황")
emp = dashboard.headcount()
left, right = st.columns(2)
with left:
    by_dept = emp.groupby("dept").size().rename("인원").reset_index()
    chart(alt.Chart(by_dept).mark_bar(color=BLUE, cornerRadiusEnd=4).encode(
        y=alt.Y("dept:N", sort="-x", title=None), x=alt.X("인원:Q", title="명"),
        tooltip=[alt.Tooltip("dept:N", title="부서"), "인원"]), alt.Step(34))
with right:
    years = emp["hire_date"].map(lambda d: (date(year, month, 28) - date.fromisoformat(d)).days // 365)
    tenure = years.value_counts().sort_index().rename_axis("근속연수").rename("인원").reset_index()
    chart(alt.Chart(tenure).mark_bar(color=BLUE, cornerRadiusEnd=4).encode(
        x=alt.X("근속연수:O", title="근속연수 (년)"), y=alt.Y("인원:Q", title="명"),
        tooltip=["근속연수", "인원"]), 220)
