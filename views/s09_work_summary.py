import pandas as pd
import streamlit as st

from erp import rules, schedule, ui, worktime

ui.header("S09")

HOUR_COLS = ["기본", "연장", "휴일", "휴일8h초과", "야간", "연장·야간", "휴일·야간"]


def h(m):
    """분 → 시간 (소수 둘째 자리)"""
    return round(m / 60, 2)


def hm(m):
    """분 → '9:54'"""
    return f"{int(m) // 60}:{int(m) % 60:02d}"


def clock(t, base):
    """같은 날이면 'HH:MM', 날짜가 넘어가면 'MM-DD HH:MM'"""
    return t.strftime("%H:%M") if t.date() == base else t.strftime("%m-%d %H:%M")


months = worktime.months_with_records()
if not months:
    st.info("출퇴근 기록이 없습니다. S08에서 먼저 입력하세요.")
    st.stop()
year, month = st.selectbox("대상 월 (출퇴근 기록이 있는 달)", months, format_func=lambda ym: f"{ym[0]}년 {ym[1]}월")
first, last = schedule.month_range(year, month)

# ---- 1. 계산 기준 ----
with st.container(border=True):
    st.markdown("**계산 기준**")
    c1, c2 = st.columns(2)
    early = c1.toggle("근무 시작 전 출근도 근로로 인정", value=False)
    extra = c2.number_input("근무 종료 후 몇 분 이상 남아야 잔업으로 볼까 (분)", 0, 120, 30, step=5)
    st.caption(ui.md("**법으로 정해진 것** — 하루 8시간·주 40시간(월~일)을 넘으면 연장 · 22~06시는 야간 · "
                     "주휴일·공휴일 근로는 휴일근로이며 날짜는 0시에 바뀜 · 자정을 넘는 근무는 시작한 날의 근무로 봄 · "
                     "분 단위로 계산하고 반올림하지 않음  \n"
                     "**회사가 정할 것** — 위 두 칸. 인터뷰로 확정합니다 (기획서 §9). 바꾸면 아래 결과가 바로 다시 계산됩니다."))

policy = rules.Policy(early_in=early, min_extra=int(extra))
daily = worktime.compute(policy, year, month)          # 달 앞뒤로 걸친 주의 기록까지 들어 있다
in_month = daily[daily["in_month"]]
weekly = worktime.weekly(daily)
week_end = (pd.to_datetime(weekly["week"]) + pd.Timedelta(days=6)).dt.strftime("%Y-%m-%d")
weekly = weekly[(weekly["week"] <= last) & (week_end >= first)]          # 이 달에 걸친 주만
cases = worktime.pick_cases(daily)

tab1, tab2, tab3 = st.tabs([f"사례별 검증 ({len(cases)}건)", "주간 집계 · 52시간", "일별 전체"])

# ---- 2. 사례별 검증 ----
with tab1:
    if not cases:
        st.info("이 달 기록에는 미리 정한 검증 사례에 맞는 근무가 없습니다. 주간·일별 탭에서 결과를 보세요.")
    else:
        labels = {c["id"]: f"{c['id']} {c['title']}" for c in cases}
        chosen = st.pills("사례", list(labels), format_func=labels.get, default=cases[0]["id"]) or cases[0]["id"]
        case = next(c for c in cases if c["id"] == chosen)
        r = daily.loc[case["index"]]
        base = pd.Timestamp(r["work_date"]).date()

        st.subheader(labels[chosen])
        st.caption(f"적용 규칙 {case['rule']}")
        st.info(ui.md(case["point"]), icon=":material/lightbulb:")

        st.markdown("**① 원본 기록**")
        st.dataframe(pd.DataFrame([{
            "사번": r["emp_no"], "이름": r["name"], "부서": r["dept"], "근무일": ui.day_label(r["work_date"]),
            "날짜 구분": r["day_type"], "근무조": f"{r['shift_code']} {r['shift_span']}", "휴게": r["break_span"],
            "출근": r["clock_in"][11:], "퇴근": r["clock_out"][5:]}]), hide_index=True, width="stretch")

        st.markdown("**② 근로로 인정한 구간**")
        c1, c2 = st.columns(2)
        c1.metric("인정 시작", clock(r["rec_start"], base), help=r["start_note"])
        c1.caption(r["start_note"])
        c2.metric("인정 끝", clock(r["rec_end"], base), help=r["end_note"])
        c2.caption(r["end_note"])
        seg_text = ", ".join(f"{clock(s, base)}~{clock(e, base)}" for s, e in r["segments"])
        seg_min = sum(rules.minutes(s, e) for s, e in r["segments"])
        st.markdown(ui.md(f"휴게를 빼면 → **{seg_text}** = 실근로 **{hm(seg_min)}** ({h(seg_min)}시간)"))

        st.markdown("**③ 조각별 분류** — 0시·06시·22시와 8시간 경계에서 자른 조각입니다")
        st.dataframe(pd.DataFrame([{
            "구간": f"{clock(a, base)} ~ {clock(b, a.date())}", "날짜 구분": dt, "분": rules.minutes(a, b),
            "시간": h(rules.minutes(a, b)), "분류": kind, "야간": "야간" if night else ""}
            for a, b, kind, night, dt in r["pieces"]]), hide_index=True, width="stretch")

        st.markdown("**④ 결과**")
        cols = st.columns(5)
        for col, k in zip(cols, ["기본", "연장", "휴일", "휴일8h초과", "야간"]):
            col.metric(k, hm(r[k]), help=f"{h(r[k])}시간")
        overlap = [f"연장이면서 야간 {hm(r['연장·야간'])}" if r["연장·야간"] else "",
                   f"휴일이면서 야간 {hm(r['휴일·야간'])}" if r["휴일·야간"] else ""]
        st.caption(" · ".join(x for x in overlap if x) or "야간과 겹치는 연장·휴일 시간 없음")

        st.markdown("**⑤ 가산율** (R2·R3·R4) — 시간 × 가산율 × 통상시급 = 가산수당. 금액 계산은 3주차(S11)")
        st.dataframe(pd.DataFrame([
            {"분류": k, "시간": h(r[k]), "가산율": f"{int(rules.PREMIUM[k] * 100)}%",
             "가산 환산 시간": h(r[k] * rules.PREMIUM[k])} for k in rules.PREMIUM if r[k]]
            or [{"분류": "가산 대상 없음"}]), hide_index=True, width="stretch")

        st.markdown("**⑥ 그 주의 흐름** — 주 40시간은 월요일부터 쌓입니다")
        same_week = daily[(daily["emp_no"] == r["emp_no"]) & (daily["week"] == r["week"])]
        st.dataframe(pd.DataFrame([{
            "근무일": ui.day_label(x["work_date"]), "날짜 구분": x["day_type"], "근무조": x["shift_code"],
            "이 근무 전 주 기본": h(x["week_regular_before"]), "기본": h(x["기본"]), "연장": h(x["연장"]),
            "휴일": h(x["휴일"]), "휴일8h초과": h(x["휴일8h초과"]), "야간": h(x["야간"]),
            "← 이 사례": "◀" if i == case["index"] else ""} for i, x in same_week.iterrows()]),
            hide_index=True, width="stretch")
        wk = weekly[(weekly["emp_no"] == r["emp_no"]) & (weekly["week"] == r["week"])].iloc[0]
        msg = f"이 주 총근로 {hm(wk['총근로'])} (연장+휴일 {hm(wk['연장+휴일'])})"
        if wk["52시간 초과"]:
            st.error(f"{msg} → 주 52시간을 {hm(wk['52시간 초과'])} 넘었습니다 (R5)", icon=":material/error:")
        else:
            st.caption(msg + " · 주 52시간 이내")

        with st.expander("내 손계산과 맞춰 보기"):
            st.caption("손으로 계산한 시간을 넣으면 시스템 결과와 비교합니다. 이 칸은 저장되지 않으니 엑셀 손계산표에도 적어 두세요.")
            cols = st.columns(5)
            mine = {k: col.number_input(k, 0.0, 24.0, step=0.01, format="%.2f", key=f"{chosen}-{k}")
                    for col, k in zip(cols, ["기본", "연장", "휴일", "휴일8h초과", "야간"])}
            diff = {k: v for k, v in mine.items() if round(v, 2) != h(r[k])}
            if not any(mine.values()):
                st.caption("아직 입력 전입니다.")
            elif diff:
                st.warning("다른 칸: " + ", ".join(f"{k} (내 계산 {v:.2f} / 시스템 {h(r[k]):.2f})" for k, v in diff.items()))
            else:
                st.success("다섯 칸 모두 일치합니다.")

        # 엑셀 손계산표용: 사례 10건 원본 + 시스템 결과 + 빈 손계산 칸
        sheet = pd.DataFrame([{
            "사례": c["id"], "제목": c["title"], "규칙": c["rule"],
            "사번": daily.loc[c["index"], "emp_no"], "이름": daily.loc[c["index"], "name"],
            "근무일": daily.loc[c["index"], "work_date"], "날짜 구분": daily.loc[c["index"], "day_type"],
            "근무조": f"{daily.loc[c['index'], 'shift_code']} {daily.loc[c['index'], 'shift_span']}",
            "휴게": daily.loc[c["index"], "break_span"],
            "출근": daily.loc[c["index"], "clock_in"], "퇴근": daily.loc[c["index"], "clock_out"],
            **{f"시스템_{k}": h(daily.loc[c["index"], k]) for k in ["기본", "연장", "휴일", "휴일8h초과", "야간"]},
            **{f"손계산_{k}": "" for k in ["기본", "연장", "휴일", "휴일8h초과", "야간"]},
        } for c in cases])
        st.download_button("사례 10건 내려받기 (엑셀 손계산표용 CSV)", sheet.to_csv(index=False).encode("utf-8-sig"),
                           "S09_검증사례_10건.csv", "text/csv", icon=":material/download:")

# ---- 3. 주간 집계 · 52시간 (R5) ----
with tab2:
    over = weekly[weekly["52시간 초과"] > 0]
    c1, c2, c3 = st.columns(3)
    c1.metric("주 52시간 초과", f"{len(over)}건")
    c2.metric("해당 인원", f"{over['emp_no'].nunique()}명")
    c3.metric("최대 주 근로", hm(weekly["총근로"].max()))
    only_over = st.toggle("52시간 넘은 주만 보기", value=True)
    view = (over if only_over else weekly).copy()
    view["주"] = view["week"].map(lambda w: f"{w[5:]} ~ {(pd.Timestamp(w) + pd.Timedelta(days=6)):%m-%d}")
    for k in HOUR_COLS + ["총근로", "연장+휴일", "52시간 초과"]:
        view[k] = view[k].map(h)
    st.dataframe(view[["emp_no", "name", "dept", "주", "기본", "연장", "휴일", "휴일8h초과", "야간",
                       "총근로", "연장+휴일", "52시간 초과", "비고"]].rename(columns=ui.LABELS),
                 hide_index=True, width="stretch")
    st.caption("총근로 = 기본 + 연장 + 휴일. 휴일근로도 주 52시간에 들어갑니다 (1주 = 휴일 포함 7일). "
               "달 경계에 걸친 주는 앞뒤 달 기록까지 더해 판단합니다. 기록이 없는 날짜가 섞인 주는 '부분 주'로 표시합니다.")

# ---- 4. 일별 전체 ----
with tab3:
    c1, c2 = st.columns(2)
    depts = c1.multiselect("부서", sorted(in_month["dept"].unique()), placeholder="전체 부서")
    kinds = c2.multiselect("날짜 구분", ["소정근로일", "휴무일", "주휴일", "공휴일"], placeholder="전체")
    view = in_month
    if depts:
        view = view[view["dept"].isin(depts)]
    if kinds:
        view = view[view["day_type"].isin(kinds)]
    view = view.copy()
    for k in HOUR_COLS:
        view[k] = view[k].map(h)
    st.caption(f"{len(view)}건 · 단위: 시간")
    st.dataframe(view[["work_date", "emp_no", "name", "dept", "shift_code", "day_type", "clock_in", "clock_out",
                       *HOUR_COLS, "start_note", "end_note"]]
                 .rename(columns={**ui.LABELS, "start_note": "시작 판단", "end_note": "끝 판단"}),
                 hide_index=True, width="stretch")

# ---- 5. 확정 ----
st.divider()
saved = worktime.saved_at(year, month)
left, right = st.columns([3, 1])
left.markdown(f"**{year}년 {month}월 근태 확정**  \n"
              + (f"마지막 확정: {saved[0]} · {saved[1]}건. 계산 기준을 바꿨다면 다시 확정해야 급여 계산에 반영됩니다."
                 if saved else "아직 확정 전입니다. 확정하면 지금 결과가 근로시간 집계 테이블에 저장되고, 급여 계산(S11)이 이 값을 씁니다."))
if right.button("지금 결과로 확정", type="primary", icon=":material/task_alt:", width="stretch"):
    at = worktime.save(daily, year, month)
    st.toast(f"{len(in_month)}건을 확정했습니다 ({at})", icon=":material/task_alt:")
    st.rerun()
