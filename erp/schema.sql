-- =========================================================
--  다온정밀 HR 미니 ERP — 테이블 정의 (17개)
--  기획서 v0.1 §5-2 기준 + 공휴일 달력(holiday) 1개 추가
-- =========================================================

PRAGMA foreign_keys = ON;

-- ---- 1. 기준정보 ----

-- 회사 설정: 회사는 하나만 둔다
CREATE TABLE company (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    name              TEXT    NOT NULL,
    industry          TEXT,
    regular_headcount INTEGER NOT NULL,              -- 상시근로자 수 → 5인 미만 분기(R11)
    weekly_hours      REAL    NOT NULL DEFAULT 40,   -- 주 소정근로시간
    monthly_hours     REAL    NOT NULL DEFAULT 209,  -- 월 소정근로시간 → 통상시급(R1)
    pay_day           INTEGER NOT NULL,              -- 급여 지급일 (다음 달 n일)
    leave_basis       TEXT    NOT NULL CHECK (leave_basis IN ('입사일', '회계연도'))
);

-- 연도별 요율표: 매년 바뀌는 값은 코드에 박지 않고 여기에 둔다
CREATE TABLE rate_table (
    year            INTEGER PRIMARY KEY,
    min_wage        INTEGER NOT NULL,        -- 최저시급 (원)
    pension_rate    REAL    NOT NULL,        -- 국민연금 근로자 부담률 (%)
    health_rate     REAL    NOT NULL,        -- 건강보험 근로자 부담률 (%)
    ltc_rate        REAL    NOT NULL,        -- 장기요양보험: 건강보험료 대비 (%)
    employment_rate REAL    NOT NULL,        -- 고용보험 근로자 부담률 (%)
    verified        INTEGER NOT NULL DEFAULT 0,  -- 공식 고시 원문과 대조했으면 1
    source_note     TEXT
);

-- 공휴일 달력: 같은 날이라도 공휴일이면 휴일근로(R3)가 된다
CREATE TABLE holiday (
    date TEXT PRIMARY KEY,                   -- 'YYYY-MM-DD'
    name TEXT NOT NULL
);

-- 공통코드: 직급·고용형태·휴가 종류·발령 종류 같은 선택지
CREATE TABLE code (
    grp  TEXT    NOT NULL,
    code TEXT    NOT NULL,
    name TEXT    NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (grp, code)
);

CREATE TABLE department (
    dept_code   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    parent_code TEXT REFERENCES department (dept_code),
    job_family  TEXT CHECK (job_family IN ('관리', '생산'))   -- 본부는 NULL
);

-- 근무조: 휴게 '위치'까지 알아야 야간근로(R4)에서 정확히 뺄 수 있다
CREATE TABLE shift (
    shift_code  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    start_time  TEXT NOT NULL,               -- 'HH:MM'
    end_time    TEXT NOT NULL,               -- 시작보다 이르면 다음 날 종료
    break_start TEXT,
    break_end   TEXT
);

CREATE TABLE pay_item (
    item_code     TEXT    PRIMARY KEY,
    name          TEXT    NOT NULL,
    kind          TEXT    NOT NULL CHECK (kind IN ('지급', '공제')),
    taxable       INTEGER NOT NULL DEFAULT 1,
    ordinary_wage INTEGER NOT NULL DEFAULT 0,    -- 통상임금 포함 여부 → 가산수당의 출발점(R1)
    sort          INTEGER NOT NULL DEFAULT 0
);

-- ---- 2. 인사 ----

-- 사원: 현재 값만 둔다. 바뀐 내역은 assignment·wage_contract에 쌓는다
CREATE TABLE employee (
    emp_no       TEXT PRIMARY KEY,           -- 입사연도 4자리 + 순번 3자리
    name         TEXT NOT NULL,
    dept_code    TEXT NOT NULL REFERENCES department (dept_code),
    rank_code    TEXT NOT NULL,              -- code.grp = '직급'
    emp_type     TEXT NOT NULL,              -- code.grp = '고용형태'
    pay_type     TEXT NOT NULL CHECK (pay_type IN ('월급', '시급')),
    shift_group  TEXT CHECK (shift_group IN ('A', 'B')),   -- 교대 조, 사무직은 NULL
    weekly_hours REAL NOT NULL DEFAULT 40,   -- 주 소정근로시간 → 15시간 미만이면 주휴·연차 제외(R6)
    hire_date    TEXT NOT NULL,
    leave_date   TEXT,
    -- 소득세 원천징수(R9)에 쓰는 값. 실무에서는 근로자가 '근로소득 원천징수 신고서'로 낸다
    tax_family      INTEGER NOT NULL DEFAULT 1 CHECK (tax_family >= 1),          -- 공제대상가족 수 (본인·배우자 각 1명 포함)
    tax_children    INTEGER NOT NULL DEFAULT 0 CHECK (tax_children >= 0),        -- 그중 8세 이상 20세 이하 자녀 수
    withholding_pct INTEGER NOT NULL DEFAULT 100 CHECK (withholding_pct IN (80, 100, 120)),   -- 근로자가 고른 원천징수 비율
    CHECK (tax_children < tax_family)
);

-- 발령 이력: 덮어쓰지 않고 한 줄씩 추가한다
CREATE TABLE assignment (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_no       TEXT NOT NULL REFERENCES employee (emp_no),
    eff_date     TEXT NOT NULL,
    kind         TEXT NOT NULL,              -- code.grp = '발령종류'
    before_value TEXT,
    after_value  TEXT
);

-- 임금 이력: 적용 시작일 기준. 인상되면 새 줄을 추가한다
CREATE TABLE wage_contract (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_no      TEXT    NOT NULL REFERENCES employee (emp_no),
    eff_date    TEXT    NOT NULL,
    base_amount INTEGER NOT NULL,            -- 월급제는 월 기본급, 시급제는 시급
    fixed_items TEXT    NOT NULL DEFAULT '{}',   -- 고정수당 {"P02": 100000, "P03": 200000}
    UNIQUE (emp_no, eff_date)
);

-- ---- 3. 근태 ----

-- 근무표: 같은 8시간도 날짜 구분에 따라 수당이 다르다
CREATE TABLE schedule (
    emp_no     TEXT NOT NULL REFERENCES employee (emp_no),
    work_date  TEXT NOT NULL,
    shift_code TEXT REFERENCES shift (shift_code),   -- 근무 없는 날은 NULL, 특근이면 휴일에도 값이 있다
    day_type   TEXT NOT NULL CHECK (day_type IN ('소정근로일', '주휴일', '휴무일', '공휴일')),
    PRIMARY KEY (emp_no, work_date)
);

-- 출퇴근 기록: 원본. 야간조는 근무를 시작한 날짜로 기록한다
CREATE TABLE attendance (
    emp_no    TEXT NOT NULL REFERENCES employee (emp_no),
    work_date TEXT NOT NULL,
    clock_in  TEXT NOT NULL,                 -- 'YYYY-MM-DD HH:MM'
    clock_out TEXT NOT NULL,
    source    TEXT NOT NULL DEFAULT '단말기',
    PRIMARY KEY (emp_no, work_date)
);

-- 근로시간 집계: 계산 결과를 남겨 급여와 대조한다 (2주차에 채운다)
CREATE TABLE work_summary (
    emp_no          TEXT NOT NULL REFERENCES employee (emp_no),
    work_date       TEXT NOT NULL,
    regular_h       REAL NOT NULL DEFAULT 0,
    overtime_h      REAL NOT NULL DEFAULT 0,
    night_h         REAL NOT NULL DEFAULT 0,
    holiday_h       REAL NOT NULL DEFAULT 0,     -- 휴일근로 8시간 이내
    holiday_over8_h REAL NOT NULL DEFAULT 0,     -- 휴일근로 8시간 초과
    computed_at     TEXT NOT NULL,
    PRIMARY KEY (emp_no, work_date)
);

-- 연차 발생: 왜 그만큼 생겼는지 근거를 남긴다
CREATE TABLE leave_grant (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_no      TEXT NOT NULL REFERENCES employee (emp_no),
    grant_date  TEXT NOT NULL,
    days        REAL NOT NULL,
    basis       TEXT NOT NULL,
    expire_date TEXT NOT NULL
);

CREATE TABLE leave_use (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_no     TEXT NOT NULL REFERENCES employee (emp_no),
    use_date   TEXT NOT NULL,
    leave_type TEXT NOT NULL,                -- code.grp = '휴가종류'
    days       REAL NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('신청', '승인', '반려'))
);

-- ---- 4. 급여 ----

CREATE TABLE payroll_run (
    run_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    pay_month TEXT NOT NULL,                 -- 귀속연월 'YYYY-MM'
    run_kind  TEXT NOT NULL DEFAULT '급여' CHECK (run_kind IN ('급여', '상여')),
    pay_date  TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT '작성중' CHECK (status IN ('작성중', '확정')),
    closed_at TEXT,
    UNIQUE (pay_month, run_kind)
);

-- 급여 상세: 금액 옆에 계산 근거를 남긴다 → 임금명세서 기재 의무(R10)
CREATE TABLE payroll_line (
    run_id    INTEGER NOT NULL REFERENCES payroll_run (run_id),
    emp_no    TEXT    NOT NULL REFERENCES employee (emp_no),
    item_code TEXT    NOT NULL REFERENCES pay_item (item_code),
    amount    INTEGER NOT NULL,
    basis     TEXT,                          -- 예: '연장 12h × 12,000원 × 0.5'
    PRIMARY KEY (run_id, emp_no, item_code)
);

-- ---- 5. 월 마감 잠금 ----
--  확정된 회차의 급여 상세는 DB가 직접 거부한다. 화면에서 실수로 고칠 길을 막는다

CREATE TRIGGER payroll_lock_insert BEFORE INSERT ON payroll_line
WHEN (SELECT status FROM payroll_run WHERE run_id = NEW.run_id) = '확정'
BEGIN
    SELECT RAISE(ABORT, '확정된 급여 회차는 수정할 수 없습니다');
END;

CREATE TRIGGER payroll_lock_update BEFORE UPDATE ON payroll_line
WHEN (SELECT status FROM payroll_run WHERE run_id = OLD.run_id) = '확정'
BEGIN
    SELECT RAISE(ABORT, '확정된 급여 회차는 수정할 수 없습니다');
END;

CREATE TRIGGER payroll_lock_delete BEFORE DELETE ON payroll_line
WHEN (SELECT status FROM payroll_run WHERE run_id = OLD.run_id) = '확정'
BEGIN
    SELECT RAISE(ABORT, '확정된 급여 회차는 수정할 수 없습니다');
END;
