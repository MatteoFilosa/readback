import csv
import os
from dataclasses import dataclass
from functools import lru_cache

from .text import fold, slug

CATALOG_DIR = os.environ.get(
    "COHORT_CATALOG", os.path.join(os.path.dirname(__file__), os.pardir, "catalog"))

DATA_START, DATA_END = "2019-01-01", "2026-09-30"

OPS = {
    "int": ("between", "lt", "le", "gt", "ge", "eq", "in"),
    "float": ("between", "lt", "le", "gt", "ge"),
    "date": ("between", "lt", "le", "gt", "ge", "eq"),
    "enum": ("eq", "ne", "in", "not_in"),
    "set": ("has", "has_any", "has_all", "has_none"),
}
LIST_OPS = {"between", "in", "not_in", "has_any", "has_all", "has_none"}

# Italian national triage scale (2019): colour codes map onto the numeric levels.
TRIAGE_COLOURS = {
    "rosso": 1, "red": 1, "rouge": 1,
    "arancione": 2, "orange": 2,
    "azzurro": 3, "blue": 3, "bleu": 3,
    "verde": 4, "green": 4, "vert": 4,
    "bianco": 5, "white": 5, "blanc": 5,
}

_SEX = {
    "female": ["f", "females", "woman", "women", "donna", "donne", "femmina", "femmine",
               "femme", "femmes"],
    "male": ["m", "males", "man", "men", "uomo", "uomini", "maschio", "maschi", "homme",
             "hommes"],
}
_SMOKING = {
    "current": ["smoker", "smokers", "smoking", "active", "fumatore", "fumatori", "fumatrice",
                "fumeur", "fumeurs"],
    "former": ["ex", "ex_smoker", "ex_smokers", "quit", "ex_fumatore", "ex_fumatori",
               "ancien_fumeur"],
    "never": ["non_smoker", "non_smokers", "nonsmoker", "non_fumatore", "non_fumatori",
              "non_fumeur", "none"],
}


@dataclass(frozen=True)
class Attr:
    key: str
    kind: str
    label: str
    lo: object = None
    hi: object = None
    values: tuple = ()
    unit: str = ""
    note: str = ""


def _rows(root, name):
    with open(os.path.join(root, name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _split(field):
    return [p.strip() for p in (field or "").split("|") if p.strip()]


class Catalog:
    def __init__(self, root: str = CATALOG_DIR):
        self.chapters = {}
        for r in _rows(root, "chapters.csv"):
            self.chapters[r["key"]] = {"name": r["name"], "icd10": r["icd10"],
                                       "terms": _split(r["terms"]), "members": []}
        self.conditions = {}
        for r in _rows(root, "conditions.csv"):
            if r["chapter"] not in self.chapters:
                raise ValueError(f"{r['key']}: unknown chapter {r['chapter']!r}")
            self.conditions[r["key"]] = {"name": r["name"], "icd10": r["icd10"],
                                         "chapter": r["chapter"], "aliases": _split(r["aliases"])}
            self.chapters[r["chapter"]]["members"].append(r["key"])
        self.regions = {}
        for r in _rows(root, "regions.csv"):
            self.regions[r["key"]] = {"name": r["name"], "name_en": r["name_en"],
                                      "area": r["area"], "population_m": float(r["population_m"]),
                                      "terms": _split(r["terms"])}
        self.areas = {}
        for r in _rows(root, "areas.csv"):
            members = _split(r["members"])
            unknown = [m for m in members if m not in self.regions]
            if unknown:
                raise ValueError(f"area {r['key']}: unknown regions {unknown}")
            self.areas[r["key"]] = {"name": r["name"], "members": members,
                                    "terms": _split(r["terms"])}
        self.cities = {}
        for r in _rows(root, "cities.csv"):
            for name in [r["name"]] + _split(r["aliases"]):
                self.cities[fold(name)] = {"name": r["name"], "region": r["region"]}

        self.attrs = {a.key: a for a in self._attrs()}
        self._alias = self._aliases()

    def _attrs(self):
        return [
            Attr("age", "int", "age", 0, 120, unit="years", note="age at admission"),
            Attr("sex", "enum", "sex", values=("female", "male")),
            Attr("region", "enum", "region", values=tuple(self.regions),
                 note="region of residence"),
            Attr("admission_date", "date", "admission date", DATA_START, DATA_END),
            Attr("length_of_stay", "int", "length of stay", 0, 365, unit="days"),
            Attr("triage", "int", "triage code", 1, 5,
                 note="1 = most urgent; colour codes 1 red, 2 orange, 3 light blue, 4 green, "
                      "5 white"),
            Attr("systolic_bp", "int", "systolic blood pressure", 50, 260, unit="mmHg",
                 note="at triage"),
            Attr("temperature", "float", "body temperature", 33.0, 43.0, unit="°C",
                 note="at triage"),
            Attr("bmi", "float", "BMI", 10.0, 70.0),
            Attr("smoking", "enum", "smoking status", values=("never", "former", "current")),
            Attr("condition", "set", "condition", values=tuple(self.conditions),
                 note="coded diagnoses on record"),
        ]

    def _aliases(self):
        cond = {}
        for key, c in self.conditions.items():
            for name in [key, c["name"]] + c["aliases"]:
                cond.setdefault(slug(name), key)
        region = {}
        for key, r in self.regions.items():
            for name in (key, r["name"], r["name_en"]):
                region.setdefault(slug(name), key)
        sex = {slug(v): v for v in _SEX}
        sex.update({slug(a): v for v, al in _SEX.items() for a in al})
        smoking = {slug(v): v for v in _SMOKING}
        smoking.update({slug(a): v for v, al in _SMOKING.items() for a in al})
        return {"condition": cond, "region": region, "sex": sex, "smoking": smoking}

    def canonical(self, attr: str, value) -> str | None:
        """Catalog key for a value the model or a user wrote, or None when there is none."""
        if not isinstance(value, str):
            return None
        table = self._alias.get(attr)
        return table.get(slug(value)) if table else None

    def families(self, attr: str) -> dict:
        """Named groups a list of this attribute can stand for: chapters or areas."""
        if attr == "condition":
            return {k: {"name": c["name"], "members": c["members"], "terms": c["terms"],
                        "phrases": False} for k, c in self.chapters.items()}
        if attr == "region":
            return {k: {"name": a["name"], "members": a["members"], "terms": a["terms"],
                        "phrases": True} for k, a in self.areas.items()}
        return {}

    def label(self, attr: str, value) -> str:
        if attr == "condition" and value in self.conditions:
            c = self.conditions[value]
            return f"{c['name']} ({c['icd10']})"
        if attr == "region" and value in self.regions:
            return self.regions[value]["name"]
        return str(value)


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return Catalog()
