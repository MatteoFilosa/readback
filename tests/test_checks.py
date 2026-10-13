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


@pytest.mark.parametrize("item", GOLD, ids=lambda g: g["id"])
@pytest.mark.parametrize("lang", LANGS)
def test_every_gold_clause_rests_on_request_words(check, item, lang):
    report = check(item[lang], item["filter"])
    assert all(report.evidence)


def test_evidence_spans_point_into_the_request(check):
    request = "Fumatori lombardi con BPCO, sopra i 65 anni, ricoverati a marzo 2024"
    r = check(request, [{"attr": "smoking", "op": "eq", "value": "current"},
                        {"attr": "condition", "op": "has", "value": "copd"},
                        {"attr": "age", "op": "gt", "value": 65},
                        {"attr": "admission_date", "op": "between",
                         "value": ["2024-03-01", "2024-03-31"]},
                        {"attr": "sex", "op": "eq", "value": "male"}])
    texts = [[e["text"] for e in ev] for ev in r.evidence]
    assert texts == [["Fumatori"], ["BPCO"], ["sopra i 65 anni"], ["marzo 2024"], []]
    assert all(request[e["start"]:e["end"]] == e["text"] for ev in r.evidence for e in ev)


@pytest.mark.parametrize("clause", [
    {"attr": "condition", "op": "has_any", "value": [["asthma"]]},
    {"attr": "region", "op": "in", "value": [["lazio"], "umbria"]},
    {"attr": "age", "op": "between", "value": {"from": 40}},
    {"attr": "age", "op": "gt", "value": None},
    {"attr": "triage", "op": "in", "value": [{"code": 1}]},
])
def test_malformed_clauses_are_reported_not_raised(check, clause):
    r = check("diabetics in Lazio aged 40 with asthma, red code", [clause])
    assert "validate" in checks_of(r, "error")
    assert not r.runnable


def test_clauses_that_cannot_both_hold_block(check):
    r = check("Patients living in Lombardy admitted in 2024",
              [{"attr": "region", "op": "eq", "value": "lombardia"},
               {"attr": "admission_date", "op": "eq", "value": "2024-01-01"},
               {"attr": "admission_date", "op": "eq", "value": "2024-12-31"}])
    assert checks_of(r, "error") == ["contradiction"]
    assert not r.runnable
    r = check("women", [{"attr": "sex", "op": "eq", "value": "female"},
                        {"attr": "sex", "op": "in", "value": ["male"]}])
    assert "contradiction" in checks_of(r, "error")


def test_a_year_does_not_source_a_single_day(check):
    r = check("Pazienti residenti in Lombardia ricoverati nel 2024",
              [{"attr": "region", "op": "eq", "value": "lombardia"},
               {"attr": "admission_date", "op": "eq", "value": "2024-01-01"}])
    assert checks_of(r) == ["provenance"]


def test_or_split_into_separate_clauses(check):
    r = check("Patients with Crohn's disease or ulcerative colitis",
              [{"attr": "condition", "op": "has", "value": "crohns_disease"},
               {"attr": "condition", "op": "has", "value": "ulcerative_colitis"}])
    assert [(i.check, i.clause) for i in r.issues] == [("conjunction", 1)]


@pytest.mark.parametrize("request_text, value, flagged", [
    ("Ex fumatori con tumore del polmone", "current", True),
    ("Ex fumatori con tumore del polmone", "former", False),
    ("Fumatori con BPCO", "current", False),
    ("Non fumatori con asma", "current", True),
    ("Never smokers with asthma", "never", False),
])
def test_named_smoking_status(check, request_text, value, flagged):
    r = check(request_text, [{"attr": "smoking", "op": "eq", "value": value}])
    assert ("value" in checks_of(r)) is flagged


def test_extra_smoking_status_is_named(check):
    r = check("Fumatori con BPCO o asma",
              [{"attr": "smoking", "op": "in", "value": ["current", "former"]},
               {"attr": "condition", "op": "has_any", "value": ["copd", "asthma"]}])
    assert [(i.check, i.clause) for i in r.issues] == [("value", 0)]
