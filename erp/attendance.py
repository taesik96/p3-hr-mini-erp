# =========================================================
#  출퇴근 입력 (S08) — 직접 입력과 엑셀 업로드
#  둘 다 같은 validate()를 거친다. 오류가 있는 줄은 DB에 넣지 않는다
# =========================================================

import io
from datetime import datetime, timedelta

import pandas as pd

from erp import db

COLUMNS = ["사번", "근무일", "출근", "퇴근"]
MAX_HOURS = 20          # 출근~퇴근이 이보다 길면 기록 오류로 본다


# ---- 1. 파일 읽기 ----

def read_upload(filename, data):
    """xlsx 또는 csv → 4개 칸 표. 칸 이름이 다르면 ValueError"""
    if filename.lower().endswith(".xlsx"):
        df = pd.read_excel(io.BytesIO(data), dtype=str)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp949")          # 한글 엑셀에서 저장한 CSV
        df = pd.read_csv(io.StringIO(text), dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"칸 이름이 양식과 다릅니다. 없는 칸: {', '.join(missing)} (양식: {', '.join(COLUMNS)})")
    return df[COLUMNS]


def template(examples):
    """업로드 양식 xlsx. examples: [(사번, 근무일, 출근, 퇴근), ...]"""
    buf = io.BytesIO()
    pd.DataFrame(examples, columns=COLUMNS).to_excel(buf, index=False, sheet_name="출퇴근")
    return buf.getvalue()


# ---- 2. 한 줄씩 검사 ----

def _date(v):
    try:
        return pd.to_datetime(str(v).strip()).date()
    except (ValueError, TypeError):
        return None


def _clock(v, day):
    """'08:03' · '08:03:00' · '2026-10-01 08:03' → (datetime, 시각만 적었는지)"""
    s = str(v).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.combine(day, datetime.strptime(s, fmt).time()), True
        except ValueError:
            pass
    try:
        return pd.to_datetime(s).to_pydatetime().replace(second=0), False
    except (ValueError, TypeError):
        return None, False


def validate(df):
    """원래 칸 + 정규화한 출근·퇴근 + 상태(새 기록 / 덮어쓰기 / 오류) + 사유"""
    employees = set(db.query("SELECT emp_no FROM employee")["emp_no"])
    sched = db.query("SELECT emp_no, work_date, shift_code FROM schedule")
    has_shift = {(r.emp_no, r.work_date): pd.notna(r.shift_code) for r in sched.itertuples()}
    existing = set(db.query("SELECT emp_no || '|' || work_date AS k FROM attendance")["k"])

    out, seen = [], set()
    for i, r in df.reset_index(drop=True).iterrows():
        why = []
        emp = str(r["사번"]).strip() if pd.notna(r["사번"]) else ""
        day = _date(r["근무일"]) if pd.notna(r["근무일"]) else None
        if not emp:
            why.append("사번 없음")
        elif emp not in employees:
            why.append("없는 사번")
        if day is None:
            why.append("근무일 형식 오류")

        cin = cout = None
        if day:
            cin, _ = _clock(r["출근"], day) if pd.notna(r["출근"]) else (None, False)
            cout, time_only = _clock(r["퇴근"], day) if pd.notna(r["퇴근"]) else (None, False)
            if cin is None:
                why.append("출근 시각 형식 오류")
            if cout is None:
                why.append("퇴근 시각 형식 오류")
            if cin and cout:
                if time_only and cout <= cin:                    # 시각만 적었으면 다음 날 퇴근(야간조)
                    cout += timedelta(days=1)
                if not timedelta(0) < cout - cin <= timedelta(hours=MAX_HOURS):
                    why.append(f"근무 시간이 0 이하이거나 {MAX_HOURS}시간 초과")
                if cin.date() != day:                            # 근무일 = 출근한 날 (야간조도 시작한 날)
                    why.append("출근 날짜가 근무일과 다름")

        key = (emp, day.isoformat() if day else "")
        if emp in employees and day:
            if key not in has_shift:
                why.append("근무표 없음 (S07에서 생성)")
            elif not has_shift[key]:
                why.append("근무 없는 날 (S07에서 특근 편성)")
        if key in seen:
            why.append("파일 안에서 중복")
        seen.add(key)

        status = "오류" if why else ("덮어쓰기" if "|".join(key) in existing else "새 기록")
        out.append({"행": i + 2, "사번": emp, "근무일": key[1],
                    "출근": cin.strftime("%Y-%m-%d %H:%M") if cin else str(r["출근"]),
                    "퇴근": cout.strftime("%Y-%m-%d %H:%M") if cout else str(r["퇴근"]),
                    "상태": status, "사유": ", ".join(why)})
    return pd.DataFrame(out)


# ---- 3. 저장 · 삭제 ----

def save(checked, source):
    """검사를 통과한 줄만 넣는다. 같은 사번·근무일이 있으면 바꾼다"""
    ok = checked[checked["상태"] != "오류"]
    conn = db.connect()
    with conn:
        conn.executemany("INSERT OR REPLACE INTO attendance VALUES (?,?,?,?,?)",
                         [(r.사번, r.근무일, r.출근, r.퇴근, source) for r in ok.itertuples()])
    conn.close()
    return len(ok)


def delete(emp_no, work_date):
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM attendance WHERE emp_no = ? AND work_date = ?", (emp_no, work_date))
    conn.close()


def confirmed(first, last):
    """그 기간 근태가 이미 확정됐는지 — 기록을 바꾸면 S09에서 다시 확정해야 한다"""
    return bool(db.query("SELECT COUNT(*) n FROM work_summary WHERE work_date BETWEEN ? AND ?",
                         (first, last))["n"][0])
