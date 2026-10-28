# =========================================================
#  소득세 원천징수 (R9) — 간이세액표 파일 읽기와 사원별 원천징수 정보
#  계산 규칙은 rules.simplified_tax(), 여기는 표를 읽고 DB를 고치는 일만 한다
# =========================================================

from functools import lru_cache
from pathlib import Path

import pandas as pd

from erp import db

TABLE_PATH = Path(__file__).resolve().parent / "tax" / "간이세액표_2026-03.csv"
EFFECTIVE = "2026-03-01"            # 이 날 이후 지급분부터 이 표를 쓴다
FAMILY = [f"가족{n}" for n in range(1, 12)]
PCT = [80, 100, 120]


@lru_cache(maxsize=1)
def table():
    """(구간 목록, 10,000천원 행). 구간 = [(이상 원, 미만 원, (가족1~11 세액))]"""
    df = pd.read_csv(TABLE_PATH)
    body = df[df["이상_천원"] < df["미만_천원"]].sort_values("이상_천원")
    anchor = df[df["이상_천원"] == df["미만_천원"]].iloc[0]
    rows = [(int(lo) * 1000, int(hi) * 1000, tuple(int(v) for v in vals))
            for lo, hi, *vals in body[["이상_천원", "미만_천원", *FAMILY]].itertuples(index=False)]
    return rows, tuple(int(anchor[c]) for c in FAMILY)


def row_for(monthly):
    """화면용: 그 월급여가 걸리는 표의 한 줄 (10,000천원 이상이면 10,000천원 행). 표 밖이면 None"""
    rows, anchor = table()
    if monthly < rows[0][0]:
        return None
    if monthly >= 10_000_000:
        label, vals = "10,000천원", anchor
    else:
        lo, hi, vals = next(r for r in rows if r[0] <= monthly < r[1])
        label = f"{lo // 1000:,} 이상 {hi // 1000:,} 미만"
    return pd.DataFrame([{"월급여(천원)": label, **{f"{n}명": v for n, v in zip(range(1, 12), vals)}}])


def set_profile(emp_no, family, children, pct):
    """원천징수 정보 고치기. 확정되지 않은 급여는 S11에서 다시 계산·저장해야 반영된다"""
    if family < 1 or children < 0 or children >= family or pct not in PCT:
        raise ValueError("공제대상가족은 1명 이상(본인 포함), 자녀 수는 가족 수보다 작아야 합니다")
    conn = db.connect()
    with conn:
        conn.execute("UPDATE employee SET tax_family = ?, tax_children = ?, withholding_pct = ? WHERE emp_no = ?",
                     (int(family), int(children), int(pct), emp_no))
    conn.close()
