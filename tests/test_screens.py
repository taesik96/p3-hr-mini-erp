# =========================================================
#  화면 연기 테스트 — 데모 상태 DB로 모든 화면을 한 번씩 열어 오류가 없는지만 본다
# =========================================================

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from erp import db

ROOT = Path(__file__).resolve().parent.parent
# 홈(views/home.py)은 st.page_link가 앱 메뉴 안에서만 동작하므로 단독으로 열지 않는다. app.py가 기본 페이지로 연다
PAGES = ["app.py", *sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "views").glob("s*.py"))]


@pytest.fixture(autouse=True)
def demo_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "erp.db")
    db.build(demo=True)                       # 배포 직후와 같은 상태: 9월 근태 확정 + 급여 저장(작성중)


@pytest.mark.parametrize("page", PAGES)
def test_화면이_오류_없이_열린다(page):
    at = AppTest.from_file(str(ROOT / page), default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value
