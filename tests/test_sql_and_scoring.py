import duckdb
import pytest

from conftest import TODAY
from cohort.checks import review
from cohort.store import Store
from eval.gold import GOLD
from eval.run import score


@pytest.mark.parametrize("item", [g for g in GOLD if not g.get("probe")], ids=lambda g: g["id"])
def test_gold_filters_compile_and_run(cat, small_db, item):
    r = review(item["en"], item["filter"], cat, TODAY)
    out = Store(small_db).run(r.where, r.params, sample=3)
    assert 0 <= out["count"] <= out["total"] == 3000


def test_compiled_sql_matches_a_hand_written_query(cat, small_db):
    r = review("x", [{"attr": "age", "op": "gt", "value": 65},
                     {"attr": "condition", "op": "has_all", "value": ["diabetes", "hypertension"]},
                     {"attr": "region", "op": "in", "value": "area:isole"}], cat, TODAY)
    got = Store(small_db).run(r.where, r.params)["count"]
    con = duckdb.connect(small_db, read_only=True)
    want = con.execute("""
        SELECT count(*) FROM patients
        WHERE age > 65 AND list_contains(conditions, 'diabetes')
          AND list_contains(conditions, 'hypertension') AND region IN ('sicilia', 'sardegna')
    """).fetchone()[0]
    assert got == want


@pytest.mark.parametrize("a,b", [
    ([{"attr": "age", "op": "gt", "value": 65}], [{"attr": "age", "op": "ge", "value": 66}]),
    ([{"attr": "triage", "op": "in", "value": [1, 2]}], [{"attr": "triage", "op": "le", "value": 2}]),
    ([{"attr": "condition", "op": "has", "value": "diabetes"},
      {"attr": "condition", "op": "has", "value": "asma"}],
     [{"attr": "condition", "op": "has_all", "value": ["asthma", "diabetes"]}]),
    ([{"attr": "region", "op": "in", "value": "area:isole"}],
     [{"attr": "region", "op": "in", "value": ["sardegna", "sicilia"]}]),
    ([{"attr": "age", "op": "ge", "value": 40}, {"attr": "age", "op": "le", "value": 60}],
     [{"attr": "age", "op": "between", "value": [40, 60]}]),
])
def test_equivalent_filters_score_exact(cat, a, b):
    assert score(a, b, cat) == "exact"


def test_scores(cat):
    gold = [{"attr": "age", "op": "gt", "value": 65},
            {"attr": "condition", "op": "has", "value": "diabetes"}]
    assert score([{"attr": "age", "op": "gt", "value": 65}], gold, cat) == "partial"
    assert score([{"attr": "sex", "op": "eq", "value": "male"}], gold, cat) == "miss"
