import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TODAY = date(2026, 10, 12)


@pytest.fixture(scope="session")
def cat():
    from cohort.catalog import get_catalog
    return get_catalog()


@pytest.fixture(scope="session")
def small_db(tmp_path_factory):
    from cohort.data import build
    path = str(tmp_path_factory.mktemp("db") / "patients.duckdb")
    build(path, n=3000, seed=1)
    return path


@pytest.fixture
def check(cat):
    from cohort.checks import review

    def run(request, filt):
        return review(request, filt, cat, TODAY)
    return run


def checks_of(report, level=None):
    return [i.check for i in report.issues if level is None or i.level == level]
