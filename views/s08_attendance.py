from datetime import date, datetime, time

import pandas as pd
import streamlit as st

from erp import attendance, db, schedule, ui

ui.header("S08")

STATUS_COLOR = {"새 기록": "#e3f4e8", "덮어쓰기": "#fff4cc", "오류": "#ffd9d9"}

year, month = st.selectbox("대상 월", schedule.MONTHS, format_func=lambda ym: f"{ym[0]}년 {ym[1]}월")
first, last = schedule.month_range(year, month)
emp = db.employees()
locked = attendance.confirmed(first, last)
if locked:
    st.info("이 달 근태는 S09에서 이미 확정됐습니다. 기록을 바꾸면 S09에서 다시 확정해야 급여에 반영됩니다.",
            icon=":material/info:")

tab1, tab2, tab3, tab4 = st.tabs(["날짜별 조회", "직접 입력", "엑셀 업로드", "기록 누락 점검"])

# ---- 1. 날짜별 조회 ----
with tab1:
    day = st.date_input("근무일", date(year, month, 1), min_value=date.fromisoformat(first),
                        max_value=date.fromisoformat(last))
    rows = db.query("""
        SELECT a.work_date, a.emp_no, s.shift_code, s.day_type, a.clock_in, a.clock_out, a.source
          FROM attendance a JOIN schedule s USING (emp_no, work_date)
         WHERE a.work_date = ? ORDER BY s.shift_code, a.emp_no""", (day.isoformat(),))
    rows = rows.merge(emp[["emp_no", "name", "dept"]], on="emp_no")
    stay = pd.to_datetime(rows["clock_out"]) - pd.to_datetime(rows["clock_in"])
    rows["체류(h)"] = (stay.dt.total_seconds() / 3600).round(2)
    st.caption(f"{len(rows)}명 출근 · 체류시간은 퇴근 − 출근이며 휴게를 빼지 않은 값입니다. 근로시간 계산은 S09에서 합니다.")
    ui.show(rows[["work_date", "emp_no", "name", "dept", "shift_code", "day_type",
                  "clock_in", "clock_out", "체류(h)", "source"]])

# ---- 2. 직접 입력 (한 건) ----
with tab2:
    st.caption("단말기 고장·카드 미지참처럼 기록이 빠졌을 때 쓰는 화면입니다. 입력 경로는 '수기'로 남습니다.")
    active = emp[emp["leave_date"].isna()]
    label = {r.emp_no: f"{r.emp_no} {r.name} ({r.dept})" for r in active.itertuples()}
    c1, c2 = st.columns(2)
    who = c1.selectbox("사원", list(label), format_func=label.get)
    work_day = c2.date_input("근무일 (야간조는 근무를 시작한 날)", date(year, month, 1),
                             min_value=date.fromisoformat(first), max_value=date.fromisoformat(last), key="input_day")

    plan = db.query("""
        SELECT s.day_type, s.shift_code, f.start_time, f.end_time, a.clock_in, a.clock_out, a.source
          FROM schedule s LEFT JOIN shift f USING (shift_code)
          LEFT JOIN attendance a USING (emp_no, work_date)
         WHERE s.emp_no = ? AND s.work_date = ?""", (who, work_day.isoformat()))
    if plan.empty:
        st.warning("이 날짜에 근무표가 없습니다. S07에서 이 달 근무표를 먼저 만드세요.", icon=":material/event_busy:")
        start_default, end_default = time(9, 0), time(18, 0)
    else:
        p = plan.iloc[0]
        has_shift = pd.notna(p["shift_code"])
        st.markdown(ui.md(f"**근무표:** {ui.day_label(work_day.isoformat())} · {p['day_type']} · "
                          + (f"{p['shift_code']} {p['start_time']}~{p['end_time']}" if has_shift
                             else "근무 없음 → S07에서 특근을 편성해야 입력할 수 있습니다")))
        if pd.notna(p["clock_in"]):
            st.markdown(ui.md(f"**지금 기록:** {p['clock_in']} ~ {p['clock_out']} ({p['source']})"))
        start_default = datetime.strptime(p["start_time"], "%H:%M").time() if has_shift else time(9, 0)
        end_default = datetime.strptime(p["end_time"], "%H:%M").time() if has_shift else time(18, 0)

    c1, c2 = st.columns(2)
    cin = c1.time_input("출근", start_default, step=60, key=f"in-{who}-{work_day}")
    cout = c2.time_input("퇴근", end_default, step=60, key=f"out-{who}-{work_day}")
    if cout <= cin:
        st.caption("퇴근이 출근보다 이르므로 다음 날 퇴근(야간조)으로 봅니다.")

    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("저장", type="primary", icon=":material/save:"):
        checked = attendance.validate(pd.DataFrame([{
            "사번": who, "근무일": work_day.isoformat(), "출근": cin.strftime("%H:%M"), "퇴근": cout.strftime("%H:%M")}]))
        r = checked.iloc[0]
        if r["상태"] == "오류":
            st.error(f"저장하지 않았습니다: {r['사유']}")
        else:
            attendance.save(checked, "수기")
            st.toast(f"{who} {work_day} 기록을 {'바꿨' if r['상태'] == '덮어쓰기' else '넣었'}습니다", icon=":material/save:")
            st.rerun()
    has_record = not plan.empty and pd.notna(plan.iloc[0]["clock_in"])
    if c2.button("이 기록 삭제", icon=":material/delete:", disabled=not has_record):
        attendance.delete(who, work_day.isoformat())
        st.toast(f"{who} {work_day} 기록을 지웠습니다", icon=":material/delete:")
        st.rerun()

# ---- 3. 엑셀 업로드 ----
with tab3:
    st.caption(f"양식: {' · '.join(attendance.COLUMNS)}. 출근·퇴근은 '08:03'처럼 시각만 적어도 되고, "
               "퇴근이 출근보다 이르면 다음 날 퇴근으로 봅니다. 근무일은 근무를 시작한 날입니다.")

    # 양식 예시: 이 달 첫 주간조·야간조 근무 한 건씩
    sample = db.query("""
        SELECT s.emp_no, s.work_date, s.shift_code, f.start_time, f.end_time
          FROM schedule s JOIN shift f USING (shift_code)
         WHERE s.work_date BETWEEN ? AND ? AND s.shift_code IN ('DAY', 'NGT')
         ORDER BY s.work_date, s.emp_no""", (first, last)).drop_duplicates("shift_code")
    examples = [(r.emp_no, r.work_date, r.start_time, r.end_time) for r in sample.itertuples()]
    st.download_button("업로드 양식 내려받기 (xlsx)", attendance.template(examples),
                       f"출퇴근_업로드양식_{year}-{month:02d}.xlsx", icon=":material/download:")

    key = st.session_state.setdefault("upload_key", 0)
    file = st.file_uploader("출퇴근 파일 (xlsx 또는 csv)", type=["xlsx", "csv"], key=f"upload-{key}")
    raw = None
    if file:
        try:
            raw = attendance.read_upload(file.name, file.getvalue())
        except ValueError as e:
            st.error(str(e))
    if raw is not None:
        checked = attendance.validate(raw)
        counts = checked["상태"].value_counts()
        c1, c2, c3 = st.columns(3)
        c1.metric("새 기록", f"{counts.get('새 기록', 0)}건")
        c2.metric("덮어쓰기", f"{counts.get('덮어쓰기', 0)}건", help="같은 사번·근무일 기록이 이미 있어 바뀝니다")
        c3.metric("오류 (반영 안 함)", f"{counts.get('오류', 0)}건")

        only_errors = st.toggle("오류만 보기", value=bool(counts.get("오류", 0)))
        view = checked[checked["상태"] == "오류"] if only_errors else checked
        st.dataframe(view.style.map(lambda v: f"background-color: {STATUS_COLOR[v]}" if v in STATUS_COLOR else "",
                                    subset=["상태"]), hide_index=True, width="stretch")
        if counts.get("오류", 0):
            st.download_button("오류 줄 내려받기 (고쳐서 다시 올리기)",
                               checked[checked["상태"] == "오류"].to_csv(index=False).encode("utf-8-sig"),
                               "출퇴근_오류.csv", "text/csv", icon=":material/download:")

        n_ok = int((checked["상태"] != "오류").sum())
        if st.button(f"정상 {n_ok}건 반영", type="primary", icon=":material/upload:", disabled=n_ok == 0):
            saved = attendance.save(checked, "엑셀")
            st.session_state["upload_key"] = key + 1          # 올린 파일 칸을 비운다
            st.toast(f"{saved}건을 반영했습니다", icon=":material/upload:")
            st.rerun()

# ---- 4. 기록 누락 점검: 근무가 잡혀 있는데 출퇴근도 승인된 휴가도 없는 날 ----
with tab4:
    today = date.today()                                    # 아직 안 온 날은 빼고 본다
    missing = db.query("""
        SELECT s.work_date, s.emp_no, s.shift_code, s.day_type
          FROM schedule s
          LEFT JOIN attendance a USING (emp_no, work_date)
          LEFT JOIN leave_use l ON l.emp_no = s.emp_no AND l.use_date = s.work_date
                               AND l.status = '승인' AND l.leave_type <> 'L2'
         WHERE s.shift_code IS NOT NULL AND a.emp_no IS NULL AND l.id IS NULL
           AND s.work_date BETWEEN ? AND ? AND s.work_date < ?""", (first, last, today.isoformat()))
    missing = missing.merge(emp[["emp_no", "name", "dept"]], on="emp_no")
    if len(missing):
        st.warning(f"{len(missing)}건 — 결근인지 기록 누락인지 확인이 필요합니다. "
                   "결근이면 그 주 주휴수당(R6)과 연차 출근율(R7)에 영향을 줍니다.", icon=":material/warning:")
    else:
        st.success("빠진 기록이 없습니다.")
    ui.show(missing)
    st.caption(f"{today:%m-%d} 이전 날짜만 봅니다. 근무표를 만들기만 하고 기록을 아직 안 올린 달은 여기에 전부 잡힙니다.")
