# =========================================================
#  화면 공통 부품 — 화면 목록, 한글 칸 이름, 머리말
# =========================================================

from datetime import date

import streamlit as st

# ---- 1. 화면 목록 (기획서 §6-1) ----
#  상태: "조회" = 샘플 데이터를 볼 수 있음, "입력" = 입력·생성 가능, "계산" = 계산 규칙 구현됨,
#        "구현" = 확정·출력 같은 기능 구현됨, "n주차" = 그때 구현
SCREENS = [
    # (ID, 메뉴, 화면, 파일, 우선순위, 상태, 아이콘, 하는 일)
    ("S01", "기준정보", "회사·요율 설정", "s01_company.py", "★", "조회", ":material/domain:",
     "상시근로자 수, 연차 기준, 연도별 요율, 공휴일 달력"),
    ("S02", "기준정보", "부서·공통코드", "s02_codes.py", "☆", "조회", ":material/account_tree:",
     "부서, 직급, 휴가 종류 관리"),
    ("S03", "기준정보", "근무조·급여항목", "s03_shift_payitem.py", "★", "조회", ":material/schedule:",
     "주간/야간조, 지급·공제 항목과 통상임금 포함 여부"),
    ("S04", "인사", "사원 등록·인사카드", "s04_employee.py", "★", "조회", ":material/badge:",
     "사원 조회, 재직 상태, 인사카드"),
    ("S05", "인사", "발령 등록", "s05_assignment.py", "☆", "조회", ":material/swap_horiz:",
     "승진·전보·퇴사 발령, 이력 조회"),
    ("S06", "인사", "임금 계약", "s06_wage.py", "★", "조회", ":material/payments:",
     "시급·기본급·고정수당 이력"),
    ("S07", "근태", "월 근무표 편성", "s07_schedule.py", "★", "입력", ":material/calendar_month:",
     "2교대 패턴으로 한 달 근무표 자동 생성"),
    ("S08", "근태", "출퇴근 입력", "s08_attendance.py", "★", "입력", ":material/login:",
     "직접 입력 + 엑셀 업로드"),
    ("S09", "근태", "근태 집계·확정", "s09_work_summary.py", "★", "계산", ":material/timer:",
     "일별 소정·연장·야간·휴일 시간 계산, 주 52시간 초과 경고"),
    ("S10", "근태", "연차 현황·휴가 승인", "s10_leave.py", "★", "조회", ":material/beach_access:",
     "자동 발생, 신청·승인, 잔여 일수"),
    ("S11", "급여", "급여 계산", "s11_payroll_calc.py", "★", "계산", ":material/calculate:",
     "귀속월 선택 → 전 직원 계산 실행"),
    ("S12", "급여", "급여대장·마감", "s12_payroll_ledger.py", "★", "구현", ":material/lock:",
     "전체 조회, 확정 시 수정 잠금"),
    ("S13", "급여", "임금명세서", "s13_payslip.py", "★", "구현", ":material/receipt_long:",
     "개인별 명세서 PDF (계산 근거 포함)"),
    ("S14", "분석", "인사 대시보드", "s14_dashboard.py", "☆", "구현", ":material/monitoring:",
     "인건비 추이, 연장근로 상위자, 52시간 위험자"),
]
SCREEN = {s[0]: s for s in SCREENS}

# ---- 2. 테이블 이름 (기획서 §5-2) ----
TABLES = {
    "company": ("기준정보", "회사 설정"), "rate_table": ("기준정보", "연도별 요율표"),
    "holiday": ("기준정보", "공휴일 달력"), "code": ("기준정보", "공통코드"),
    "department": ("기준정보", "부서"), "shift": ("기준정보", "근무조"),
    "pay_item": ("기준정보", "급여항목"), "employee": ("인사", "사원"),
    "assignment": ("인사", "발령 이력"), "wage_contract": ("인사", "임금 이력"),
    "schedule": ("근태", "근무표"), "attendance": ("근태", "출퇴근 기록"),
    "work_summary": ("근태", "근로시간 집계"), "leave_grant": ("근태", "연차 발생"),
    "leave_use": ("근태", "휴가 사용"), "payroll_run": ("급여", "급여 회차"),
    "payroll_line": ("급여", "급여 상세"),
}

# ---- 3. 칸 이름: DB는 영어, 화면은 한글 ----
LABELS = {
    "emp_no": "사번", "name": "이름", "dept": "부서", "dept_code": "부서코드", "rank": "직급",
    "emp_type": "고용형태", "pay_type": "급여형태", "shift_group": "교대 조",
    "weekly_hours": "주 소정시간", "hire_date": "입사일", "leave_date": "퇴사일",
    "tax_family": "공제대상가족", "tax_children": "8~20세 자녀", "withholding_pct": "원천징수 비율(%)",
    "eff_date": "적용일", "kind": "구분", "before_value": "변경 전", "after_value": "변경 후",
    "base_amount": "기본급·시급", "work_date": "근무일", "shift_code": "근무조", "shift": "근무조",
    "day_type": "날짜 구분", "clock_in": "출근", "clock_out": "퇴근", "source": "입력 경로",
    "grant_date": "발생일", "days": "일수", "basis": "근거", "expire_date": "소멸일",
    "use_date": "사용일", "leave_type": "휴가 종류", "status": "상태",
    "year": "연도", "min_wage": "최저시급", "pension_rate": "국민연금(%)", "health_rate": "건강보험(%)",
    "ltc_rate": "장기요양(건보료 대비 %)", "employment_rate": "고용보험(%)", "verified": "원문 대조",
    "source_note": "출처 메모", "date": "날짜", "parent": "상위 부서", "job_family": "직군",
    "start_time": "시작", "end_time": "종료", "break_start": "휴게 시작", "break_end": "휴게 종료",
    "item_code": "항목코드", "taxable": "과세", "ordinary_wage": "통상임금 포함",
    "grp": "그룹", "code": "코드", "sort": "순서", "table": "테이블", "rows": "행 수",
    "pay_month": "귀속연월", "run_kind": "급여 구분", "pay_date": "지급일", "closed_at": "확정일",
}


def header(screen_id):
    """화면 제목 + 하는 일 + 상태 배지"""
    sid, menu, title, _, prio, status, _, desc = SCREEN[screen_id]
    st.title(f"{sid} {title}")
    st.caption(f"{menu} · {desc}")
    if status == "조회":
        st.badge(f"{prio} 샘플 데이터 조회", icon=":material/visibility:", color="green")
    elif status == "입력":
        st.badge(f"{prio} 입력·생성 가능", icon=":material/edit_note:", color="violet")
    elif status == "구현":
        st.badge(f"{prio} 기능 구현", icon=":material/check_circle:", color="violet")
    elif status == "계산":
        st.badge(f"{prio} 계산 구현 · 손계산 검증 전", icon=":material/calculate:", color="blue")
    else:
        st.badge(f"{prio} {status} 구현 예정", icon=":material/construction:", color="orange")


STATUS_TEXT = {"조회": "샘플 조회", "입력": "입력 가능", "계산": "계산 구현", "구현": "기능 구현"}


def day_label(iso):
    """'2026-09-23' → '09-23(수)'"""
    return f"{iso[5:]}({'월화수목금토일'[date.fromisoformat(iso).weekday()]})"


def md(text):
    """마크다운에서 '22~06시'의 '~' 두 개가 취소선으로 바뀌지 않게 막는다"""
    return text.replace("~", r"\~")


def show(df, **kwargs):
    """칸 이름을 한글로 바꿔서 표로 보여준다"""
    st.dataframe(df.rename(columns=LABELS), hide_index=True, width="stretch", **kwargs)


def planned(week, rules, steps):
    """아직 만들지 않은 화면: 언제, 어떤 규칙으로, 무엇을 할지"""
    st.info(f"{week}에 구현합니다. 지금은 자리만 잡아 두었습니다.", icon=":material/construction:")
    left, right = st.columns(2)
    with left:
        st.markdown("**처리 순서**")
        st.markdown("\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))
    with right:
        st.markdown("**쓰는 계산 규칙** (기획서 §7)")
        st.markdown("\n".join(f"- {r}" for r in rules))
