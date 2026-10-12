import pytest

from conftest import checks_of
from eval.gold import GOLD, LANGS


@pytest.mark.parametrize("item", [g for g in GOLD if not g.get("probe")], ids=lambda g: g["id"])
@pytest.mark.parametrize("lang", LANGS)
def test_gold_filters_are_quiet(check, item, lang):
    report = check(item[lang], item["filter"])
    assert report.runnable
    assert report.issues == []


@pytest.mark.parametrize("item", [g for g in GOLD if g.get("probe")], ids=lambda g: g["id"])
@pytest.mark.parametrize("lang", LANGS)
def test_probes_are_flagged(check, item, lang):
    assert check(item[lang], item["filter"]).issues


def test_invented_condition_blocks(check):
    r = check("Patients with long COVID", [{"attr": "condition", "op": "has", "value": "long_covid"}])
    assert "validate" in checks_of(r, "error")
    assert not r.runnable


def test_empty_filter_blocks(check):
    r = check("Patients with long COVID", [])
    assert checks_of(r) == ["refusal"]
    assert not r.runnable


def test_dropped_and_added_clauses(check):
    r = check("Patients aged 18 or younger admitted with a stroke",
              [{"attr": "age", "op": "le", "value": 18},
               {"attr": "region", "op": "eq", "value": "lazio"}])
    msgs = " ".join(i.message for i in r.issues if i.check == "coverage")
    assert "mentions condition" in msgs
    assert "region" in msgs


def test_admitted_alone_does_not_demand_a_date(check):
    r = check("Patients admitted with a stroke",
              [{"attr": "condition", "op": "has", "value": "stroke"}])
    assert r.issues == []


def test_near_set_with_an_outsider(check):
    r = check("Patients with a cardiovascular disease",
              [{"attr": "condition", "op": "has_any",
                "value": ["hypertension", "heart_failure", "atrial_fibrillation", "lung_cancer"]}])
    assert "near_set" in checks_of(r)


def test_one_region_for_a_whole_area(check):
    r = check("Pazienti del Sud con BPCO",
              [{"attr": "region", "op": "eq", "value": "campania"},
               {"attr": "condition", "op": "has", "value": "copd"}])
    assert "near_set" in checks_of(r)


def test_named_members_are_not_a_near_set(check):
    r = check("Pazienti con ipertensione o scompenso cardiaco",
              [{"attr": "condition", "op": "has_any", "value": ["hypertension", "heart_failure"]}])
    assert r.issues == []


@pytest.mark.parametrize("request_text,op,flagged", [
    ("Patients with diabetes and asthma", "has_any", True),
    ("Pazienti con diabete e asma", "has_any", True),
    ("Patients with diabetes or asthma", "has_any", False),
    ("Patients with diabetes or asthma", "has_all", True),
    ("Patients between 30 and 50 with diabetes or asthma", "has_any", False),
])
def test_conjunction(check, request_text, op, flagged):
    r = check(request_text, [{"attr": "condition", "op": op, "value": ["diabetes", "asthma"]}])
    assert ("conjunction" in checks_of(r)) is flagged


def test_unstated_numbers_and_dates(check):
    r = check("Very sick elderly patients", [{"attr": "triage", "op": "le", "value": 2},
                                             {"attr": "age", "op": "ge", "value": 65}])
    assert checks_of(r, "assumption") == ["provenance", "provenance"]
    r = check("Patients admitted during the 2023 summer heatwave",
              [{"attr": "admission_date", "op": "between", "value": ["2023-06-01", "2023-08-31"]}])
    assert checks_of(r, "assumption") == ["provenance"]


@pytest.mark.parametrize("request_text,value", [
    ("Patients admitted in 2024", ["2024-01-01", "2024-12-31"]),
    ("Pazienti ricoverati a marzo 2025", ["2025-03-01", "2025-03-31"]),
    ("Patients admitted between 2024-02-10 and 2024-05-01", ["2024-02-10", "2024-05-01"]),
    ("Patients admitted in the last 6 months", ["2026-04-15", "2026-10-12"]),
    ("Pazienti ricoverati l'anno scorso", ["2025-01-01", "2025-12-31"]),
])
def test_stated_dates_are_sourced(check, request_text, value):
    r = check(request_text, [{"attr": "admission_date", "op": "between", "value": value}])
    assert "provenance" not in checks_of(r)


def test_off_by_one_is_the_same_bound(check):
    r = check("Patients under 18 with asthma", [{"attr": "age", "op": "le", "value": 17},
                                                {"attr": "condition", "op": "has", "value": "asthma"}])
    assert r.issues == []


def test_triage_colour_is_a_source(check):
    r = check("Pazienti in codice arancione", [{"attr": "triage", "op": "eq", "value": 2}])
    assert r.issues == []
    assert any("triage 2" in line for line in r.explanation)


def test_city_answered_with_its_region(check):
    r = check("Asthma patients from Milan", [{"attr": "condition", "op": "has", "value": "asthma"},
                                             {"attr": "region", "op": "eq", "value": "lombardia"}])
    assert checks_of(r) == ["provenance"]


def test_unresolved_shortcuts_block(check):
    for value in ("event:heatwave", "near(Milano, 30)"):
        attr = "admission_date" if value.startswith("event") else "region"
        r = check("x", [{"attr": attr, "op": "in" if attr == "region" else "between",
                         "value": value}])
        assert "unresolved" in checks_of(r, "error")


def test_shortcut_is_explained(check):
    r = check("Patients with any cardiovascular disease",
              [{"attr": "condition", "op": "has_any", "value": "chapter:circulatory"}])
    assert r.issues == []
    assert r.explanation[0].startswith("chapter:circulatory = ")


def test_numbers_that_belong_to_other_attributes_are_not_ages(check):
    for text, clause in [
        ("Temperature above 39", {"attr": "temperature", "op": "gt", "value": 39}),
        ("Uomini con BMI pari o superiore a 35", {"attr": "bmi", "op": "ge", "value": 35}),
        ("Ricoveri con degenza superiore a 30 giorni",
         {"attr": "length_of_stay", "op": "gt", "value": 30}),
    ]:
        filt = [clause] + ([{"attr": "sex", "op": "eq", "value": "male"}]
                           if text.startswith("Uomini") else [])
        assert check(text, filt).issues == [], text
