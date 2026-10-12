"""Synthetic admissions. No real patient is behind any row.

Prevalences are rough and only meant to make cohorts look plausible: conditions rise with age,
some depend on sex, smoking and BMI, and a few follow from others (diabetes and hypertension
raise kidney and heart disease).
"""
import argparse
import os
from datetime import date, datetime

import duckdb
import numpy as np
import pandas as pd

from .catalog import DATA_END, DATA_START, get_catalog

# key: (prevalence at 60, change in log-odds per decade)
_PREV = {
    "hiv": (0.004, -0.1), "chronic_hepatitis_b": (0.008, 0.0),
    "chronic_hepatitis_c": (0.01, 0.1), "tuberculosis": (0.002, 0.0),
    "breast_cancer": (0.0006, 0.35), "lung_cancer": (0.01, 0.5),
    "colorectal_cancer": (0.012, 0.5), "prostate_cancer": (0.03, 0.7),
    "melanoma": (0.006, 0.3), "leukaemia": (0.004, 0.3), "lymphoma": (0.005, 0.3),
    "iron_deficiency_anaemia": (0.05, 0.2), "sickle_cell_disease": (0.002, -0.2),
    "immunodeficiency": (0.002, 0.0),
    "diabetes": (0.12, 0.45), "hypothyroidism": (0.05, 0.3), "hyperlipidaemia": (0.25, 0.4),
    "dementia": (0.01, 1.0), "schizophrenia": (0.006, -0.1), "bipolar_disorder": (0.01, -0.1),
    "depression": (0.07, 0.05), "anxiety_disorder": (0.07, -0.1),
    "alcohol_use_disorder": (0.015, 0.0),
    "alzheimers_disease": (0.006, 1.1), "parkinsons_disease": (0.005, 0.9),
    "epilepsy": (0.008, 0.0), "multiple_sclerosis": (0.002, -0.2), "migraine": (0.05, -0.3),
    "hypertension": (0.38, 0.55), "ischaemic_heart_disease": (0.06, 0.6),
    "heart_failure": (0.025, 0.8), "atrial_fibrillation": (0.03, 0.8),
    "cerebrovascular_disease": (0.02, 0.7), "peripheral_artery_disease": (0.025, 0.6),
    "venous_thromboembolism": (0.015, 0.4),
    "asthma": (0.06, -0.2), "copd": (0.05, 0.6), "bronchiectasis": (0.005, 0.4),
    "interstitial_lung_disease": (0.004, 0.6),
    "liver_cirrhosis": (0.01, 0.3), "crohns_disease": (0.003, -0.2),
    "ulcerative_colitis": (0.004, -0.1), "gerd": (0.12, 0.2), "coeliac_disease": (0.008, -0.1),
    "rheumatoid_arthritis": (0.01, 0.3), "osteoarthritis": (0.2, 0.6),
    "osteoporosis": (0.04, 0.7), "gout": (0.02, 0.4), "systemic_lupus": (0.0003, -0.1),
    "chronic_kidney_disease": (0.06, 0.7), "benign_prostatic_hyperplasia": (0.2, 0.8),
    "endometriosis": (0.04, 0.0),
}
_FEMALE_ONLY = {"endometriosis"}
_MALE_ONLY = {"prostate_cancer", "benign_prostatic_hyperplasia"}
# log-odds shift for women
_SEX_SHIFT = {"breast_cancer": 3.9, "hypothyroidism": 0.8, "depression": 0.4, "migraine": 0.8,
              "osteoporosis": 1.2, "systemic_lupus": 2.0, "alcohol_use_disorder": -0.8,
              "gout": -1.2, "ischaemic_heart_disease": -0.5, "multiple_sclerosis": 0.7}
# applied after the conditions they depend on are drawn
_LATE = {
    "chronic_kidney_disease": {"diabetes": 0.9, "hypertension": 0.5},
    "ischaemic_heart_disease": {"diabetes": 0.5, "hypertension": 0.5, "hyperlipidaemia": 0.6},
    "heart_failure": {"hypertension": 0.6, "ischaemic_heart_disease": 1.0},
    "atrial_fibrillation": {"hypertension": 0.4, "heart_failure": 0.8},
    "cerebrovascular_disease": {"hypertension": 0.6, "atrial_fibrillation": 0.8},
    "peripheral_artery_disease": {"diabetes": 0.6},
    "dementia": {"cerebrovascular_disease": 0.7},
}
_SMOKE = {"copd": 1.6, "lung_cancer": 2.0, "ischaemic_heart_disease": 0.6,
          "peripheral_artery_disease": 1.0, "cerebrovascular_disease": 0.4}
_OBESE = {"diabetes": 1.0, "hypertension": 0.7, "osteoarthritis": 0.5, "gerd": 0.4,
          "heart_failure": 0.4}
_TRIAGE_P = [0.02, 0.12, 0.38, 0.35, 0.13]
_LOS_FACTOR = np.array([0, 2.6, 1.8, 1.1, 0.5, 0.25])


def _logit(p):
    return np.log(p / (1 - p))


def generate(n: int = 200_000, seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    cat = get_catalog()
    rng = np.random.default_rng(seed)

    child = rng.random(n) < 0.12
    age = np.where(child, rng.integers(0, 18, n),
                   np.clip(rng.normal(63, 17, n), 18, 102)).astype(int)
    female = rng.random(n) < 0.51
    regions = list(cat.regions)
    weights = np.array([cat.regions[r]["population_m"] for r in regions])
    region = rng.choice(regions, n, p=weights / weights.sum())
    span = (date.fromisoformat(DATA_END) - date.fromisoformat(DATA_START)).days
    admitted = np.datetime64(DATA_START) + rng.integers(0, span + 1, n).astype("timedelta64[D]")

    smoke = np.full(n, "never", dtype=object)
    u = rng.random(n)
    adult = age >= 18
    current_p = np.where(female, 0.18, 0.26)
    former_p = np.clip(0.12 + 0.004 * (age - 18), 0.12, 0.4)
    smoke[adult & (u < current_p)] = "current"
    smoke[adult & (u >= current_p) & (u < current_p + former_p)] = "former"
    smoke[(age >= 14) & (age < 18) & (u < 0.05)] = "current"

    bmi = np.where(adult, rng.normal(26.3, 4.8, n) + 0.04 * (age - 45),
                   rng.normal(18.5, 3.5, n))
    bmi = np.round(np.clip(bmi, 11, 60), 1)

    keys = list(cat.conditions)
    has = {}
    decades = (age - 60) / 10
    damp = np.where(age < 18, 1.5, 0.0)
    current = smoke == "current"
    former = smoke == "former"
    obese = bmi >= 30

    def draw(key):
        p0, slope = _PREV[key]
        z = _logit(p0) + slope * decades - damp * (slope > 0.3)
        z = z + np.where(female, _SEX_SHIFT.get(key, 0.0), 0.0)
        z = z + _SMOKE.get(key, 0.0) * (current + 0.5 * former)
        z = z + _OBESE.get(key, 0.0) * obese
        for dep, w in _LATE.get(key, {}).items():
            z = z + w * has[dep]
        hit = rng.random(n) < 1 / (1 + np.exp(-z))
        if key in _MALE_ONLY:
            hit &= ~female
        if key in _FEMALE_ONLY:
            hit &= female & (age >= 15) & (age <= 55)
        return hit

    for key in keys:
        if key == "obesity" or key in _LATE:
            continue
        has[key] = draw(key)
    has["obesity"] = rng.random(n) < np.where(obese, 0.65, 0.01)
    for key in _LATE:
        has[key] = draw(key)
    if "infectious" in cat.chapters:
        infectious = np.any([has[k] for k in cat.chapters["infectious"]["members"]], axis=0)
    else:
        infectious = np.zeros(n, dtype=bool)

    old = age >= 75
    p = np.array(_TRIAGE_P)
    triage = rng.choice(np.arange(1, 6), n, p=p)
    triage = np.where(old & (rng.random(n) < 0.2), np.maximum(triage - 1, 1), triage)

    n_cond = np.sum([has[k] for k in keys], axis=0)
    los = rng.lognormal(np.log(3.5), 0.8, n) * _LOS_FACTOR[triage] * (1 + 0.08 * n_cond)
    los = np.clip(np.round(los), 0, 365).astype(int)

    fever = rng.random(n) < (0.08 + 0.1 * infectious + 0.05 * (triage <= 2))
    temp = rng.normal(36.8, 0.35, n) + fever * rng.uniform(1.0, 3.0, n)
    temp = np.round(np.clip(temp, 34.0, 42.5), 1)

    sbp = np.where(adult, rng.normal(115 + 0.45 * (age - 30), 12, n), rng.normal(102, 9, n))
    sbp = sbp + 18 * has["hypertension"] + np.where(triage == 1, rng.normal(0, 25, n), 0)
    sbp = np.clip(np.round(sbp), 60, 250).astype(int)

    patients = pd.DataFrame({
        "id": np.arange(1, n + 1), "age": age,
        "sex": np.where(female, "female", "male"), "region": region,
        "admission_date": admitted, "length_of_stay": los, "triage": triage,
        "systolic_bp": sbp, "temperature": temp, "bmi": bmi, "smoking": smoke.astype(str),
    })
    matrix = np.column_stack([has[k] for k in keys])
    rows, cols = np.nonzero(matrix)
    long = pd.DataFrame({"id": rows + 1, "condition": np.array(keys, dtype=object)[cols]})
    return patients, long


def build(path: str, n: int = 200_000, seed: int = 7) -> int:
    patients, long = generate(n, seed)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = duckdb.connect(tmp)
    con.register("p", patients)
    con.register("l", long)
    con.execute("""
        CREATE TABLE patients AS
        SELECT p.id, p.age, p.sex, p.region, CAST(p.admission_date AS DATE) AS admission_date,
               p.length_of_stay, p.triage, p.systolic_bp, p.temperature, p.bmi, p.smoking,
               coalesce(c.conditions, []::VARCHAR[]) AS conditions
        FROM p LEFT JOIN (
            SELECT id, list(condition ORDER BY condition) AS conditions FROM l GROUP BY id
        ) c USING (id)
        ORDER BY p.id
    """)
    con.execute("CREATE TABLE meta (key VARCHAR, value VARCHAR)")
    con.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("rows", str(n)), ("seed", str(seed)), ("data_start", DATA_START),
        ("data_end", DATA_END), ("built", datetime.now().isoformat(timespec="seconds"))])
    con.close()
    os.replace(tmp, path)
    return n


def main():
    ap = argparse.ArgumentParser(description="Build the synthetic admissions database.")
    ap.add_argument("--db", default=os.environ.get("COHORT_DB", "data/patients.duckdb"))
    ap.add_argument("--n", type=int, default=int(os.environ.get("COHORT_ROWS", "200000")))
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    build(args.db, args.n, args.seed)
    print(f"{args.n} synthetic admissions written to {args.db}")


if __name__ == "__main__":
    main()
