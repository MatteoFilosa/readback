"""Deterministic checks that compare a request with the filter drafted from it.

None of them calls a model. Each returns Issues the panel shows next to the clause they concern;
only errors stop a filter from running, everything else is for the clinician to read.
"""
import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

from .catalog import TRIAGE_COLOURS, Catalog, get_catalog
from .filters import compile_where, normalize, render, validate
from .issues import ASSUMPTION, ERROR, WARNING, Issue
from .resolve import is_macro, macro_key, resolve
from .text import fold, has_phrase, hits, stem, tokens

# "*" marks a prefix, anything else matches a whole word.
_WORDS = {
    "age": ["age", "aged", "ages", "eta", "anni", "years", "ans", "old", "elderly", "elder*",
            "anzian*", "giovan*", "jeune*", "young*", "vieux", "vecchi*", "child*", "bambin*",
            "enfant*", "pediatr*", "paediatr*", "adolesc*", "teen*", "infant*", "neonat*",
            "newborn*", "geriatr*", "senior*", "minorenn*", "maggiorenn*", "adult*",
            "octogen*", "ottanten*", "novanten*"],
    "sex": ["female", "females", "male", "males", "woman", "women", "man", "men", "donna",
            "donne", "femmina", "femmine", "femminile", "uomo", "uomini", "maschio", "maschi",
            "maschile", "femme", "femmes", "homme", "hommes", "sex", "sesso", "sexe", "gender"],
    "region": ["region*", "resid*", "abitant*", "living", "live", "lives", "vivono", "vive",
               "habitant*", "km", "near", "vicino", "around", "intorno", "provinc*", "citta",
               "city"],
    "length_of_stay": ["stay", "stays", "degenz*", "length*", "sejour*"],
    "triage": ["triage*", "esi", "sick", "severe", "severely", "severity", "severita", "grave",
               "gravi", "gravemente", "gravissim*", "critic*"] + list(TRIAGE_COLOURS),
    "systolic_bp": ["systol*", "sistol*", "pressur*", "pression*", "tension*", "mmhg", "bp",
                    "sbp"],
    "temperature": ["temperat*", "fever*", "febbr*", "fievr*", "febril*", "pyrex*", "degrees",
                    "gradi", "degres", "celsius"],
    "bmi": ["bmi", "imc", "overweight*", "sovrappes*", "surpoids", "underweight*", "sottopes*",
            "corpore*"],
    "smoking": ["smok*", "fumat*", "fumo", "fuma", "fumano", "tabag*", "tabac*", "cigar*",
                "sigar*", "nicotin*", "fumeur*"],
}
# Words that make a clause plausible without demanding one: "patients admitted with a stroke"
# does not ask for a date range, but a date clause on it is not unrequested either.
_WEAK = {
    "admission_date": ["admit*", "admis*", "ricover*", "ammess*", "hospitalis*", "hospitaliz*",
                       "ospedalizz*"],
    "length_of_stay": ["days", "day", "giorni", "giorno", "jours", "nights", "notti", "weeks",
                       "settimane", "longer", "durat*", "lunga", "lunghe"],
    "triage": ["urgen*", "emergen*", "codice", "code"],
    "bmi": ["weight*", "peso", "poids"],
}
_GENERIC = {
    "other", "chronic", "cronica", "cronico", "croniche", "cronici", "chronique", "disease",
    "diseases", "disorder", "disorders", "malattia", "malattie", "maladie", "morbo", "syndrome",
    "sindrome", "primary", "system", "systemic", "sistemico", "certain", "mechanism",
    "related", "high", "major", "maligno", "maligna", "della", "delle", "dello", "degli",
    "disturbo", "trouble", "troubles", "abuse", "infection", "infezione", "carcinoma",
    "tumore", "cancer", "use",
}
_ACRONYMS = {"hiv", "aids", "sida", "copd", "bpco", "ckd", "chf", "vte", "dvt", "bph", "ild",
             "avc", "hbv", "hcv", "afib"}
_EXTRA_ATTRS = {"hypertension": {"systolic_bp"}, "obesity": {"bmi"}}

_MONTHS = {
    1: ["january", "gennaio", "janvier"], 2: ["february", "febbraio", "fevrier"],
    3: ["march", "marzo", "mars"], 4: ["april", "aprile", "avril"],
    5: ["maggio"], 6: ["june", "giugno", "juin"], 7: ["july", "luglio", "juillet"],
    8: ["august", "agosto", "aout"], 9: ["september", "settembre", "septembre"],
    10: ["october", "ottobre", "octobre"], 11: ["november", "novembre"],
    12: ["december", "dicembre", "decembre"],
}
_SEASONS = ["summer", "winter", "spring", "autumn", "estate", "inverno", "primavera",
            "autunno", "hiver", "printemps", "automne"]
_UNITS = {"day": 1, "days": 1, "giorni": 1, "giorno": 1, "jours": 1, "week": 7, "weeks": 7,
          "settimane": 7, "semaines": 7, "month": 30, "months": 30, "mesi": 30, "mois": 30,
          "year": 365, "years": 365, "anni": 365, "ans": 365}
_RELATIVE = re.compile(
    r"\b(?:last|past|previous|ultim[ie]|derni(?:er|ers|ere|eres))\s+(\d+\s+)?"
    r"(days?|weeks?|months?|years?|giorni|settimane|mesi|anni|jours|semaines|mois|ans)\b"
    r"|\b(?:last|this|current)\s+(year|month)\b"
    r"|\b(anno|mese)\s+(scorso|corrente)\b|\bquest\s+(anno|mese)\b"
    r"|\b(annee|mois)\s+(derniere|dernier|en cours)\b|\bcette\s+annee\b")
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")

_CMP = (r"(?:over|under|above|below|older|younger|more|less|plus|moins|oltre|sopra|sotto|piu|"
        r"meno|superiore|inferiore|maggiore|minore|almeno|least|most|ultra)")
_FILL = (r"(?:\s+(?:than|di|de|d|a|i|gli|le|the|of|que|ai|agli|alle|or|o|ou|equal|to|uguale|"
         r"pari))*")
_AGE_CMP = re.compile(rf"\b{_CMP}{_FILL}\s+(\d{{1,3}})\b")
_AGE_AFTER = re.compile(r"\b(\d{1,3})\s+(?:(?:years?|anni|ans)\s+)?(?:or|o|ou)\s+"
                        rf"{_CMP}\b")
_AGE_RANGE = re.compile(r"\b(?:between|tra|fra|from|da|entre|de|dai|dagli)\s+(\d{1,3})\s+"
                        r"(?:and|e|to|a|et|ai|agli|alle)\s+(\d{1,3})\b")
_AGE_PLUS = re.compile(r"\b(\d{1,3})\s*\+")
_NOT_AGE_UNITS = {"days", "day", "giorni", "giorno", "jours", "nights", "notti", "weeks",
                  "settimane", "mmhg", "gradi", "degrees", "degres", "kg", "km", "mesi",
                  "months", "mois", "c", "celsius"}
_RIVAL_ATTRS = ("length_of_stay", "triage", "systolic_bp", "temperature", "bmi")
_RIVAL_EXTRA = ["level*", "livell*", "niveau*", "score*", "punteggi*"]

_AND = {"and", "e", "ed", "et", "both", "entrambi", "entrambe", "sia", "insieme", "together"}
_OR = {"or", "o", "oppure", "ou", "either", "any", "qualsiasi", "qualunque", "almeno"}


@dataclass(frozen=True)
class Term:
    key: str
    prefix: bool
    attrs: frozenset
    strong: bool = True


def _term(word, attrs, strong=True):
    if word.endswith("*"):
        return Term(word[:-1], True, frozenset(attrs), strong)
    return Term(word, False, frozenset(attrs), strong)


def _stems(text):
    out = []
    for tok in fold(text).split():
        if tok in _GENERIC:
            continue
        if tok in _ACRONYMS:
            out.append((tok, False))
        elif len(tok) >= 4:
            out.append(stem(tok))
    return out


@dataclass
class Vocab:
    terms: list = field(default_factory=list)
    phrases: list = field(default_factory=list)
    condition_names: dict = field(default_factory=dict)
    region_terms: dict = field(default_factory=dict)
    rivals: list = field(default_factory=list)


@lru_cache(maxsize=4)
def vocab(cat: Catalog) -> Vocab:
    """A full condition name counts as a mention; one of its words alone only excuses a
    clause, so "pressione arteriosa" does not demand a peripheral artery disease clause."""
    v = Vocab()
    for attr, words in _WORDS.items():
        v.terms += [_term(w, {attr}) for w in words]
    for attr, words in _WEAK.items():
        v.terms += [_term(w, {attr}, strong=False) for w in words]
    for key, c in cat.conditions.items():
        attrs = frozenset({"condition"} | _EXTRA_ATTRS.get(key, set()))
        variants = [s for s in (_stems(n) for n in [c["name"]] + c["aliases"]) if s]
        v.condition_names[key] = variants
        v.phrases += [(tuple(s), attrs) for s in variants]
        v.terms += [Term(k, p, attrs, strong=False) for s in variants for k, p in s]
    for ch in cat.chapters.values():
        v.terms += [Term(fold(t), True, frozenset({"condition"})) for t in ch["terms"]]
    for key, r in cat.regions.items():
        v.region_terms[key] = [fold(t) for t in r["terms"]]
        v.terms += [Term(fold(t), True, frozenset({"region"})) for t in r["terms"]]
    rival_words = [w for a in _RIVAL_ATTRS for w in _WORDS.get(a, []) + _WEAK.get(a, [])]
    v.rivals = [_term(w, set()) for w in rival_words + _RIVAL_EXTRA]
    return v


def _relative_spans(folded):
    return [m.span() for m in _RELATIVE.finditer(folded)]


def _strip_spans(folded, spans):
    for a, b in reversed(spans):
        folded = folded[:a] + " " + folded[b:]
    return folded


def _claimed_by_rival(folded, start, end, v: Vocab):
    before = folded[:start].split()[-4:]
    after = folded[end:].split()[:1]
    if after and after[0] in _NOT_AGE_UNITS:
        return True
    return any(hits(before, t.key, t.prefix) for t in v.rivals)


def _mentions_age(folded, raw, v: Vocab):
    for rx in (_AGE_CMP, _AGE_AFTER, _AGE_RANGE):
        for m in rx.finditer(folded):
            nums = [int(g) for g in m.groups() if g and g.isdigit()]
            if any(n > 120 for n in nums):
                continue
            num_start = m.start(1)
            if not _claimed_by_rival(folded, m.start() if rx is not _AGE_AFTER else num_start,
                                     m.end(), v):
                return True
    for m in _AGE_PLUS.finditer(raw):
        if int(m.group(1)) <= 120:
            return True
    return False


def mentions(request: str, cat: Catalog):
    """What the request talks about -> (strong mentions as attr alternatives, weak attrs)."""
    v = vocab(cat)
    folded = fold(request)
    rel = _relative_spans(folded)
    plain = _strip_spans(folded, rel)
    toks = plain.split()
    strong, weak = set(), set()
    for t in v.terms:
        if not hits(toks, t.key, t.prefix):
            continue
        if t.strong:
            strong.add(t.attrs)
        else:
            weak.update(t.attrs)
    for stems, attrs in v.phrases:
        if all(hits(toks, k, p) for k, p in stems):
            strong.add(attrs)
    if _mentions_age(plain, request, v):
        strong.add(frozenset({"age"}))
    date_words = [w for ws in _MONTHS.values() for w in ws] + _SEASONS
    if rel or _YEAR.search(folded) or any(w in toks for w in date_words):
        strong.add(frozenset({"admission_date"}))
    if re.search(r"\b\d+\s*km\b", folded):
        strong.add(frozenset({"region"}))
    if any(has_phrase(folded, fold(p)) for a in cat.areas.values() for p in a["terms"]):
        strong.add(frozenset({"region"}))
    if _cities(folded, cat):
        strong.add(frozenset({"region"}))
    return strong, weak


def _cities(folded, cat: Catalog):
    return [info for name, info in cat.cities.items() if has_phrase(folded, name)]


_WORD = re.compile(r"[^\W_]+")
_KM = re.compile(r"\b\d+\s*km\b")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _spans(request):
    """Folded tokens -> (folded text, [(token, offset in folded text, start, end in request)])."""
    toks, pos = [], 0
    for m in _WORD.finditer(request or ""):
        for t in fold(m.group()).split():
            toks.append((t, pos, m.start(), m.end()))
            pos += len(t) + 1
    return " ".join(t[0] for t in toks), toks


def evidence(request: str, resolved: list, cat: Catalog) -> list[list[dict]]:
    """For each clause, the words of the request it rests on. Empty means nothing in the
    request supports it: the model chose it."""
    v = vocab(cat)
    folded, toks = _spans(request)
    relative = {i for i, t in enumerate(toks)
                for a, b in _relative_spans(folded) if a <= t[1] < b}

    def within(spans):
        spans = list(spans)
        return {i for i, t in enumerate(toks) for a, b in spans if a <= t[1] < b}

    def find(phrase, prefix=True):
        rx = re.compile(rf"\b{re.escape(phrase)}" + ("" if prefix else r"\b"))
        return within(m.span() for m in rx.finditer(folded)) if phrase else set()

    def words(attr, strong=True):
        return set().union(*(find(t.key, t.prefix) for t in v.terms
                             if t.attrs == {attr} and t.strong == strong)) - relative

    def numbers(values, tol):
        nums = [x for x in values if isinstance(x, (int, float)) and not isinstance(x, bool)]
        spans = [m.span() for m in _NUM.finditer(request or "")
                 if any(abs(float(m.group().replace(",", ".")) - x) <= tol for x in nums)]
        hit = {i for i, t in enumerate(toks) for a, b in spans if a <= t[2] < b}
        for rx in (_AGE_CMP, _AGE_AFTER, _AGE_RANGE):
            for m in rx.finditer(folded):
                span = within([m.span()])
                if span & hit:
                    hit |= span
        return hit

    def named(key):
        out = set()
        for variant in v.condition_names.get(key, []):
            parts = [find(k, p) for k, p in variant]
            if all(parts):
                out |= set().union(*parts)
        return out

    def region(key):
        out = set().union(*(find(t) for t in v.region_terms.get(key, [])))
        for name, info in cat.cities.items():
            if info["region"] == key:
                out |= find(name, False)
        return out

    def own(cl):
        attr, spec = cl["attr"], cat.attrs[cl["attr"]]
        raw = str(cl.get("unresolved") or cl.get("shortcut") or "")
        value = cl.get("value")
        values = value if isinstance(value, list) else [value]
        kind, _, key = macro_key(raw).partition(":") if is_macro(raw) else ("", "", "")
        if attr == "condition":
            if kind == "chapter":
                return set().union(*(find(fold(t)) for t in
                                     cat.chapters.get(key, {}).get("terms", [])))
            return set().union(*(named(x) for x in values if isinstance(x, str)))
        if attr == "region":
            if kind == "area":
                return set().union(*(find(fold(t), False) for t in
                                     cat.areas.get(key, {}).get("terms", [])))
            if kind == "near":
                place = key.rsplit(":", 1)[0].replace("_", " ")
                return find(place, False) | within(m.span() for m in _KM.finditer(folded))
            return set().union(*(region(x) for x in values if isinstance(x, str)))
        if spec.kind == "date":
            dates = []
            for x in values:
                try:
                    dates.append(date.fromisoformat(x))
                except (TypeError, ValueError):
                    pass
            years = {str(d.year) for d in dates} or set(_YEAR.findall(folded))
            months = {d.month for d in dates}
            out = set().union(*(find(y, False) for y in years))
            out |= set().union(*(find(w, False) for m in months for w in _MONTHS[m]))
            if kind == "event":
                out |= set().union(*(find(w, False) for w in _SEASONS))
            return out | within(_relative_spans(folded))
        if attr in ("sex", "smoking"):
            return within([span for val, span in _value_mentions(folded, attr, cat)
                           if val in values])
        if spec.kind in ("int", "float"):
            hit = numbers(values, 0 if attr == "triage" else 1 if spec.kind == "int" else 1e-6)
            if attr == "triage":
                hit |= set().union(*(find(w, False) for w, c in TRIAGE_COLOURS.items()
                                     if c in values))
            return hit | words(attr) if hit else set()
        return set()

    out = []
    for cl in resolved:
        idx = set()
        if isinstance(cl, dict) and cl.get("attr") in cat.attrs:
            idx = own(cl) or words(cl["attr"]) or words(cl["attr"], strong=False)
        runs = []
        for i in sorted(idx):
            if runs and i == runs[-1][-1] + 1:
                runs[-1].append(i)
            else:
                runs.append([i])
        out.append([{"start": toks[r[0]][2], "end": toks[r[-1]][3],
                     "text": request[toks[r[0]][2]:toks[r[-1]][3]]} for r in runs])
    return out


def coverage(request: str, filt: list, cat: Catalog) -> list[Issue]:
    strong, weak = mentions(request, cat)
    used = {cl.get("attr") for cl in filt if isinstance(cl, dict)}
    issues = []
    for alts in sorted(strong, key=lambda a: sorted(a)):
        if not alts & used:
            labels = " or ".join(cat.attrs[a].label for a in sorted(alts))
            issues.append(Issue("coverage", WARNING,
                                f"The request mentions {labels}, but no clause filters on it.",
                                attr="condition" if "condition" in alts else sorted(alts)[0]))
    mentioned = set().union(weak, *strong)
    for i, cl in enumerate(filt):
        attr = cl.get("attr") if isinstance(cl, dict) else None
        if attr in cat.attrs and attr not in mentioned:
            issues.append(Issue("coverage", WARNING,
                                f"This clause filters on {cat.attrs[attr].label}, which the "
                                f"request does not mention.", i))
    return issues


def _named(attr, value, toks, cat: Catalog) -> bool:
    v = vocab(cat)
    if attr == "condition":
        return any(all(hits(toks, k, p) for k, p in variant)
                   for variant in v.condition_names.get(value, []))
    return any(hits(toks, t, True) for t in v.region_terms.get(value, []))


def _asks_for(family, toks, folded) -> bool:
    if family["phrases"]:
        return any(has_phrase(folded, fold(p)) for p in family["terms"])
    return any(hits(toks, fold(t), True) for t in family["terms"])


def near_sets(request: str, resolved: list, cat: Catalog) -> list[Issue]:
    """A hand-written list that is almost a named group (a chapter, an area)."""
    folded = fold(request)
    toks = folded.split()
    issues = []
    for i, cl in enumerate(resolved):
        if not isinstance(cl, dict) or "unresolved" in cl or "shortcut" in cl:
            continue
        attr, op, value = cl.get("attr"), cl.get("op"), cl.get("value")
        if attr not in ("condition", "region") or op in ("has_none", "not_in", "ne"):
            continue
        listed = set(value) if isinstance(value, list) else {value}
        if not listed or not all(isinstance(x, str) for x in listed):
            continue
        fams = cat.families(attr)

        def closeness(k):
            m = set(fams[k]["members"])
            return len(listed & m) / len(listed | m), len(listed & m)

        key = max(fams, key=closeness)
        fam = fams[key]
        members = set(fam["members"])
        common, missing, extra = listed & members, members - listed, listed - members
        if not common or (not missing and not extra):
            continue
        if all(_named(attr, x, toks, cat) for x in listed):
            continue
        asked = _asks_for(fam, toks, folded)
        if missing and not extra and not asked:
            continue
        if extra and not asked and len(common) < 2:
            continue
        noun = "conditions" if attr == "condition" else "regions"
        short = f"{'chapter' if attr == 'condition' else 'area'}:{key}"
        names = lambda xs: ", ".join(cat.label(attr, x) for x in sorted(xs))
        if extra:
            msg = (f"This list is close to {fam['name']} ({short}): {len(common)} of its "
                   f"{len(members)} {noun}, plus {names(extra)} from outside it.")
        else:
            msg = (f"This list holds {len(common)} of the {len(members)} {noun} of "
                   f"{fam['name']}, missing {names(missing)}. The request names the whole "
                   f"group: {short} selects all of it.")
        issues.append(Issue("near_set", WARNING, msg, i))
    return issues


def _numbers(request):
    return [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", request)]


def _shift(d: date, days: int) -> date:
    return d - timedelta(days=days)


def _date_sources(request: str, today: date):
    """Dates a request makes explicit -> (years, months, exact dates, approximate dates)."""
    folded = fold(request)
    toks = folded.split()
    years = {int(y) for y in _YEAR.findall(folded)}
    months = {m for m, ws in _MONTHS.items() if any(w in toks for w in ws)}
    exact = set()
    for y, m, d in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", request):
        exact.add((int(y), int(m), int(d)))
    for d, m, y in re.findall(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", request):
        exact.add((int(y), int(m), int(d)))
    approx = []
    for m in _RELATIVE.finditer(folded):
        text = m.group(0)
        n = re.search(r"\d+", text)
        unit = next((u for u in _UNITS if re.search(rf"\b{u}\b", text)), None)
        if n and unit:
            approx += [_shift(today, int(n.group()) * _UNITS[unit]), today]
        elif any(w in text for w in ("last", "scorso", "derniere", "dernier", "previous")):
            if "month" in text or "mese" in text or "mois" in text:
                first = today.replace(day=1)
                prev = _shift(first, 1)
                approx += [prev.replace(day=1), prev]
            else:
                years.add(today.year - 1)
        else:
            years.add(today.year)
            approx.append(today)
    return years, months, exact, approx


def _date_sourced(d: date, years, months, exact, approx) -> bool:
    if (d.year, d.month, d.day) in exact:
        return True
    if any(abs((d - a).days) <= 7 for a in approx):
        return True
    if d.year not in years:
        return False
    if (d.month, d.day) in ((1, 1), (12, 31)):
        return True
    last = calendar.monthrange(d.year, d.month)[1]
    return d.month in months and d.day in (1, last)


def provenance(request: str, resolved: list, cat: Catalog, today: date) -> list[Issue]:
    """Numbers and dates in the filter that nothing in the request states."""
    nums = _numbers(request)
    toks = tokens(request)
    colours = {v for w, v in TRIAGE_COLOURS.items() if w in toks}
    srcs = _date_sources(request, today)
    issues = []
    for i, cl in enumerate(resolved):
        if not isinstance(cl, dict) or "unresolved" in cl:
            continue
        spec = cat.attrs.get(cl.get("attr"))
        if spec is None or spec.kind not in ("int", "float", "date"):
            continue
        values = cl["value"] if isinstance(cl.get("value"), list) else [cl.get("value")]
        loose = []
        for x in values:
            if spec.kind == "date":
                try:
                    d = date.fromisoformat(x)
                except (TypeError, ValueError):
                    continue
                # "in 2024" sources 1 January as a range bound, not as the only day.
                day = (set(), set(), *srcs[2:]) if cl.get("op") in ("eq", "ne") else srcs
                if not _date_sourced(d, *day):
                    loose.append(str(d))
                continue
            if not isinstance(x, (int, float)) or isinstance(x, bool):
                continue
            tol = 1 if spec.kind == "int" else 1e-6
            if any(abs(x - n) <= tol for n in nums):
                continue
            if spec.key == "triage" and x in colours:
                continue
            loose.append(f"{x:g}")
        if loose:
            one = len(loose) == 1
            issues.append(Issue(
                "provenance", ASSUMPTION,
                f"{', '.join(loose)} {'is' if one else 'are'} not in the request: the model "
                f"chose {'this value' if one else 'these values'} for {spec.label}. "
                f"Confirm or edit.", i))
    return issues


def conjunction(request: str, resolved: list, cat: Catalog) -> list[Issue]:
    """'and' read as 'or' between conditions, or the reverse."""
    toks = set(tokens(request))
    has_and, has_or = bool(toks & _AND), bool(toks & _OR)
    issues = []
    for i, cl in enumerate(resolved):
        if not isinstance(cl, dict) or cl.get("attr") != "condition" or "shortcut" in cl:
            continue
        value = cl.get("value")
        if not isinstance(value, list) or len(value) < 2:
            continue
        if cl.get("op") == "has_any" and has_and and not has_or:
            issues.append(Issue("conjunction", WARNING,
                                "The request joins these conditions with 'and', but the clause "
                                "accepts patients with any one of them. Use 'has all of' if "
                                "every condition is required.", i))
        elif cl.get("op") == "has_all" and has_or and not has_and:
            issues.append(Issue("conjunction", WARNING,
                                "The request joins these conditions with 'or', but the clause "
                                "requires all of them at once.", i))
    required = [i for i, cl in enumerate(resolved)
                if isinstance(cl, dict) and cl.get("attr") == "condition"
                and "shortcut" not in cl and cl.get("op") in ("has", "has_all")]
    if len(required) > 1 and has_or and not has_and:
        issues += [Issue("conjunction", WARNING,
                         "The request joins these conditions with 'or', but separate clauses "
                         "require every one of them. One 'has any of' clause accepts either.", i)
                   for i in required[1:]]
    return issues


def _value_mentions(folded: str, attr: str, cat: Catalog) -> list:
    """Enum values the request names -> [(value, span)], longest phrase first, so that
    "ex fumatori" reads as former and not also as current."""
    table = cat._alias.get(attr, {})
    phrases = sorted(((k.replace("_", " "), v) for k, v in table.items() if len(k) > 1),
                     key=lambda p: -len(p[0]))
    found, taken = [], []
    for phrase, value in phrases:
        for m in re.finditer(rf"\b{re.escape(phrase)}\b", folded):
            a, b = m.span()
            if not any(a < y and x < b for x, y in taken):
                taken.append((a, b))
                found.append((value, (a, b)))
    return found


def value_reading(request: str, resolved: list, cat: Catalog) -> list[Issue]:
    """A sex or smoking status the request names, answered with another one."""
    folded = fold(request)
    issues = []
    for i, cl in enumerate(resolved):
        if not isinstance(cl, dict) or cl.get("attr") not in ("sex", "smoking"):
            continue
        if cl.get("op") not in ("eq", "in"):
            continue
        value = cl.get("value")
        chosen = set(value) if isinstance(value, list) else {value}
        named = {v for v, _ in _value_mentions(folded, cl["attr"], cat)}
        extra = chosen - named
        if not named or not extra:
            continue
        label = cat.attrs[cl["attr"]].label
        if chosen & named:
            msg = (f"The request names {label} {' or '.join(sorted(named))}; the clause also "
                   f"accepts {', '.join(map(str, sorted(extra)))}.")
        else:
            msg = (f"The request reads as {label} {' or '.join(sorted(named))}, but the clause "
                   f"selects {', '.join(map(str, sorted(chosen)))}.")
        issues.append(Issue("value", WARNING, msg, i))
    return issues


def _range(spec, op, v):
    step = 1 if spec.kind in ("int", "date") else 1e-9
    num = (lambda x: date.fromisoformat(x).toordinal()) if spec.kind == "date" else float
    try:
        if op == "between":
            return num(v[0]), num(v[1])
        x = num(v)
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return {"eq": (x, x), "ge": (x, None), "gt": (x + step, None), "le": (None, x),
            "lt": (None, x - step)}.get(op)


def contradiction(resolved: list, cat: Catalog) -> list[Issue]:
    """Clauses on one attribute that no patient can satisfy together."""
    ranges, sets, issues = {}, {}, []
    for i, cl in enumerate(resolved):
        if not isinstance(cl, dict) or "unresolved" in cl:
            continue
        spec = cat.attrs.get(cl.get("attr"))
        if spec is None:
            continue
        op, v = cl.get("op"), cl.get("value")
        if spec.kind in ("int", "float", "date"):
            r = _range(spec, op, v)
            if r is None:
                continue
            lo, hi = ranges.get(spec.key, (None, None))
            lo = r[0] if lo is None else lo if r[0] is None else max(lo, r[0])
            hi = r[1] if hi is None else hi if r[1] is None else min(hi, r[1])
            ranges[spec.key] = (lo, hi)
            empty = lo is not None and hi is not None and lo > hi
        elif spec.kind == "enum" and op in ("eq", "in"):
            vals = set(v) if isinstance(v, list) else {v}
            sets[spec.key] = sets.get(spec.key, vals) & vals
            empty = not sets[spec.key]
        else:
            continue
        if empty:
            issues.append(Issue("contradiction", ERROR,
                                f"This clause and an earlier one on {spec.label} cannot both "
                                f"hold: the filter would select no one.", i))
    return issues


def city_scope(request: str, resolved: list, cat: Catalog) -> list[Issue]:
    """A city in the request answered with its whole region."""
    named = _cities(fold(request), cat)
    issues = []
    for i, cl in enumerate(resolved):
        if not isinstance(cl, dict) or cl.get("attr") != "region" or "unresolved" in cl:
            continue
        value = cl.get("value")
        regions = value if isinstance(value, list) else [value]
        for city in named:
            if city["region"] in regions:
                where = ", ".join(cat.label("region", r) for r in regions[:4])
                where += ", ..." if len(regions) > 4 else ""
                issues.append(Issue(
                    "provenance", ASSUMPTION,
                    f"The request names {city['name']}; the data records only the region of "
                    f"residence, so this clause selects everyone in {where}.", i))
    return issues


@dataclass
class Report:
    filter: list
    resolved: list
    readable: list
    explanation: list
    issues: list
    sql: str
    runnable: bool
    evidence: list = field(default_factory=list)
    where: str = ""
    params: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"filter": self.filter, "readable": self.readable,
                "explanation": self.explanation, "evidence": self.evidence,
                "issues": [x.as_dict() for x in self.issues], "sql": self.sql,
                "runnable": self.runnable}


def review(request: str, raw_filter, cat: Catalog | None = None,
           today: date | None = None) -> Report:
    """Normalise, resolve and check a drafted filter against the request it came from."""
    cat = cat or get_catalog()
    today = today or date.today()
    filt, readings = normalize(raw_filter, cat)
    resolved, trace, unresolved = resolve(filt, cat)
    issues = []
    if not filt:
        issues.append(Issue("refusal", ERROR,
                            "No clause: running this would select every patient. Rephrase the "
                            "request or add a clause by hand."))
    issues += [Issue("unresolved", ERROR, reason, i) for i, reason in unresolved]
    issues += validate(resolved, cat)
    issues += coverage(request, filt, cat)
    # A clause that already blocks is not read further: its value may have any shape.
    broken = {x.clause for x in issues if x.level == ERROR}
    clean = [None if i in broken else cl for i, cl in enumerate(resolved)]
    issues += contradiction(clean, cat)
    issues += near_sets(request, clean, cat)
    issues += conjunction(request, clean, cat)
    issues += value_reading(request, clean, cat)
    issues += provenance(request, clean, cat, today)
    issues += city_scope(request, clean, cat)

    toks = tokens(request)
    glossary = [f"'{w}' = triage {v} (colour code)" for w, v in TRIAGE_COLOURS.items()
                if w in toks and any(isinstance(c, dict) and c.get("attr") == "triage"
                                     for c in filt)]
    runnable = bool(filt) and not any(x.level == ERROR for x in issues)
    sql, where, params = "", "", []
    if runnable:
        shown, where, params = compile_where(resolved, cat)
        sql = f"SELECT *\nFROM patients\nWHERE {shown}"
    return Report(filter=filt, resolved=resolved,
                  readable=[render(c, cat) for c in resolved],
                  explanation=trace + readings + glossary, issues=issues, sql=sql,
                  runnable=runnable, evidence=evidence(request, resolved, cat),
                  where=where, params=params)
