from datetime import date, timedelta

import pandas as pd
import streamlit as st

from erp import db, schedule, ui

ui.header("S07")

SHORT = {"DAY": "주", "NGT": "야", "OFC": "사", "PT": "단"}
SHIFT_NAME = {"DAY": "주간조", "NGT": "야간조", "OFC": "사무", "PT": "단시간", None: "근무 없음"}
COLOR = {"주": "#fff4cc", "야": "#dfe3ff", "사": "#eef2f5", "단": "#eef2f5", "공": "#ffd9d9"}


def cell(shift, kind):
    """근무조와 날짜 구분을 한 글자로. 휴일에 근무하면 '특'을 붙인다"""
    if pd.notna(shift):                      # 빈 값이 NaN으로 오므로 notna로 확인
        return SHORT[shift] if kind == "소정근로일" else "특" + SHORT[shift]
    return {"공휴일": "공", "주휴일": "·"}.get(kind, "")


def paint(v):
    if v.startswith("특"):
        return "background-color: #ffc98a; font-weight: 700"
    return f"background-color: {COLOR[v]}" if v in COLOR else ""


year, month = st.selectbox("대상 월", schedule.MONTHS, format_func=lambda ym: f"{ym[0]}년 {ym[1]}월")
first, last = schedule.month_range(year, month)
status = schedule.month_status(year, month)
emp = db.employees()

tab1, tab2, tab3 = st.tabs(["월 근무표", "자동 생성", "특근·근무 변경"])

# ---- 1. 사원 × 날짜 격자 ----
with tab1:
    sched = db.query("SELECT emp_no, work_date, shift_code, day_type FROM schedule WHERE work_date BETWEEN ? AND ?",
                     (first, last))
    if sched.empty:
        st.info("이 달 근무표가 아직 없습니다. '자동 생성' 탭에서 만드세요.", icon=":material/calendar_add_on:")
    else:
        depts = list(dict.fromkeys(db.query(
            "SELECT name FROM department WHERE job_family IS NOT NULL ORDER BY dept_code")["name"]))
        dept = st.segmented_control("부서", depts, default="가공팀") or "가공팀"
        view = sched.merge(emp[["emp_no", "name", "dept", "shift_group"]], on="emp_no")
        view = view[view["dept"] == dept]
        view["칸"] = [cell(s, k) for s, k in zip(view["shift_code"], view["day_type"])]
        view["날짜"] = view["work_date"].map(ui.day_label).str[3:]
        view["사원"] = (view["emp_no"] + " " + view["name"] + " "
                      + view["shift_group"].fillna("").map(lambda g: f"[{g}조]" if g else ""))
        grid = view.pivot(index="사원", columns="날짜", values="칸").fillna("")
        grid = grid[sorted(grid.columns)]
        st.dataframe(grid.style.map(paint), width="stretch", height=38 * (len(grid) + 1))
        st.caption("주 = 주간조 · 야 = 야간조 · 사 = 사무 · 단 = 단시간 · 공 = 공휴일 · '·' = 주휴일 · "
                   "빈칸 = 휴무일 또는 입사 전 · **특 = 휴일 특근**")

        st.subheader("휴일 특근")
        special = view[(view["day_type"] != "소정근로일") & view["shift_code"].notna()]
        if special.empty:
            st.caption("이 부서는 이 달 휴일 특근이 없습니다.")
        else:
            ui.show(special.groupby(["work_date", "day_type", "shift_code"]).size()
                    .rename("인원").reset_index())

# ---- 2. 교대 패턴 → 한 달 생성 ----
with tab2:
    if status["attendance"]:
        st.warning(f"이 달에는 출퇴근 기록 {status['attendance']:,}건이 있어 다시 생성할 수 없습니다. "
                   "근무표를 통째로 바꾸면 기록과 어긋나기 때문입니다. '특근·근무 변경' 탭을 쓰세요.",
                   icon=":material/lock:")

    st.markdown("**교대 패턴**")
    c1, c2, c3 = st.columns(3)
    base = c1.date_input("기준 주 — 이 주에 A조가 주간조", date(2026, 8, 31))
    base -= timedelta(days=base.weekday())               # 어떤 날을 골라도 그 주 월요일로
    cycle = c2.radio("교대 주기", [1, 2], format_func=lambda n: f"{n}주마다", horizontal=True)
    pt_days = c3.multiselect("단시간 근로자 근무 요일", list(range(5)), default=[0, 2, 4],
                             format_func=lambda i: "월화수목금"[i])
    pattern = schedule.Pattern(base_monday=base, cycle_weeks=cycle, part_time_days=tuple(pt_days))
    st.caption(f"기준 주 {base:%m-%d}(월)부터 {cycle}주마다 A조·B조가 주간·야간을 바꿉니다. "
               "관리직은 사무 근무, 단시간 근로자는 고른 요일만 근무합니다. 교대 형태는 인터뷰로 확정합니다 (기획서 §9-1).")

    hol = status["holidays"]
    if hol.empty:
        st.warning("이 달에 등록된 공휴일이 없습니다. 정말 없는지 S01 공휴일 달력을 확인하세요.", icon=":material/event_busy:")
    else:
        st.caption("이 달 공휴일: " + ", ".join(f"{ui.day_label(d)} {n}" for d, n in zip(hol["date"], hol["name"])))

    preview = schedule.generate(year, month, pattern)
    st.markdown(f"**미리 보기** — {preview['emp_no'].nunique()}명 × 날짜 = {len(preview):,}칸")
    staffing = (preview.dropna(subset=["shift_code"])
                .assign(근무조=lambda d: d["shift_code"].map(SHIFT_NAME), 날짜=lambda d: d["work_date"].map(ui.day_label))
                .pivot_table(index="근무조", columns="날짜", values="emp_no", aggfunc="count", fill_value=0))
    st.dataframe(staffing, width="stretch")
    st.caption("날짜별 근무조 인원입니다. 주간·야간 인원이 주마다 바뀌는지 확인하세요. 휴일 특근은 생성 후 '특근·근무 변경'에서 넣습니다.")

    overwrite = True
    if status["schedule"] and not status["attendance"]:
        overwrite = st.checkbox(f"이 달 기존 근무표 {status['schedule']:,}칸을 지우고 새로 만듭니다")
    if st.button("근무표 저장", type="primary", icon=":material/save:",
                 disabled=bool(status["attendance"]) or not overwrite):
        schedule.save_month(preview, year, month)
        st.toast(f"{year}년 {month}월 근무표 {len(preview):,}칸을 저장했습니다", icon=":material/save:")
        st.rerun()

# ---- 3. 특근 편성 · 근무 변경 ----
with tab3:
    st.caption("휴일(주휴일·공휴일·휴무일)에 근무조를 넣으면 특근이 되고, 평일 근무조를 바꾸면 근무 변경이 됩니다. "
               "날짜 구분은 달력이 정하므로 그대로 두고 근무조만 바꿉니다.")
    c1, c2, c3 = st.columns([1, 2, 1])
    day = c1.date_input("날짜", date(year, month, 1), min_value=date.fromisoformat(first),
                        max_value=date.fromisoformat(last))
    active = emp[emp["leave_date"].isna() | (emp["leave_date"] >= day.isoformat())]
    label = {r.emp_no: f"{r.emp_no} {r.name} ({r.dept}{' ' + r.shift_group + '조' if pd.notna(r.shift_group) else ''})"
             for r in active.itertuples()}
    picked = c2.multiselect("사원", list(label), format_func=label.get, placeholder="사원 선택")
    new_shift = c3.selectbox("바꿀 근무조", ["DAY", "NGT", "OFC", "PT", None], format_func=SHIFT_NAME.get)

    if picked:
        now = db.query(f"""
            SELECT s.emp_no, s.day_type, s.shift_code, a.clock_in IS NOT NULL AS 출퇴근기록
              FROM schedule s LEFT JOIN attendance a USING (emp_no, work_date)
             WHERE s.work_date = ? AND s.emp_no IN ({','.join('?' * len(picked))})""",
                       (day.isoformat(), *picked))
        now["shift_code"] = now["shift_code"].map(lambda s: SHIFT_NAME[s if pd.notna(s) else None])
        now["출퇴근기록"] = now["출퇴근기록"].map({1: "있음", 0: ""})
        st.markdown(f"**{ui.day_label(day.isoformat())} 현재**")
        ui.show(now)

    if st.button("적용", icon=":material/edit_calendar:", disabled=not picked):
        done, refused = schedule.change(picked, day.isoformat(), new_shift)
        if done:
            st.toast(f"{len(done)}명을 {SHIFT_NAME[new_shift]}(으)로 바꿨습니다", icon=":material/edit_calendar:")
        for e, why in refused:
            st.error(f"{e}: {why}")
        if done and status["attendance"]:
            st.info("출퇴근 기록이 있는 달입니다. S09에서 근태를 다시 확정해야 급여에 반영됩니다.")
        if done and not refused:
            st.rerun()
