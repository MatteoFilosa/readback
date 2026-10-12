"""The filter language: a list of {attr, op, value} clauses, ANDed together."""
from datetime import date

from .catalog import DATA_END, DATA_START, LIST_OPS, OPS, Catalog
from .issues import ERROR, WARNING, Issue
from .resolve import is_macro
from .text import slug

_ATTR_ALIAS = {
    "comorbidity": "condition", "comorbidities": "condition", "conditions": "condition",
    "diagnosis": "condition", "diagnoses": "condition", "disease": "condition",
    "diseases": "condition",
    "gender": "sex",
    "residence": "region", "region_of_residence": "region",
    "los": "length_of_stay", "stay": "length_of_stay", "length_of_stay_days": "length_of_stay",
    "bp": "systolic_bp", "sbp": "systolic_bp", "systolic": "systolic_bp",
    "blood_pressure": "systolic_bp", "systolic_blood_pressure": "systolic_bp",
    "temp": "temperature", "body_temperature": "temperature",
    "date": "admission_date", "admission": "admission_date", "admitted": "admission_date",
    "smoker": "smoking", "smoking_status": "smoking",
    "triage_level": "triage", "triage_code": "triage", "esi": "triage",
}
_OP_ALIAS = {
    "=": "eq", "==": "eq", "equals": "eq", "is": "eq", "!=": "ne", "<>": "ne",
    ">": "gt", ">=": "ge", "gte": "ge", "<": "lt", "<=": "le", "lte": "le",
    "range": "between", "not in": "not_in", "nin": "not_in",
    "contains": "has", "includes": "has", "any": "has_any", "contains_any": "has_any",
    "all": "has_all", "contains_all": "has_all", "none": "has_none", "not_has": "has_none",
    "lacks": "has_none",
}
_SQL_OP = {"lt": "<", "le": "<=", "gt": ">", "ge": ">=", "eq": "=", "ne": "<>"}
_SHOW_OP = {"lt": "<", "le": "≤", "gt": ">", "ge": "≥", "eq": "=", "ne": "≠"}


def _to_number(kind, v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        try:
            v = float(v.strip().replace(",", "."))
        except ValueError:
            return v
    if kind == "int" and isinstance(v, float) and v.is_integer():
        return int(v)
    if kind == "float" and isinstance(v, int):
        return float(v)
    return v


def _clean(cat, attr, kind, v, readings):
    if kind in ("int", "float"):
        return _to_number(kind, v)
    if kind == "date":
        return v[:10] if isinstance(v, str) and len(v) > 10 and v[4:5] == "-" else v
    if kind in ("enum", "set") and isinstance(v, (str, int)):
        key = cat.canonical(attr, str(v))
        if key is None:
            return slug(str(v))
        if slug(str(v)) != key:
            readings.append(f"'{v}' read as {cat.label(attr, key)}")
        return key
    return v


def normalize(filt, cat: Catalog):
    """Canonical clauses -> (clauses, readings), readings being the aliases that were applied."""
    if not isinstance(filt, list):
        return [], []
    out, readings = [], []
    for clause in filt:
        if not isinstance(clause, dict):
            out.append(clause)
            continue
        attr = slug(str(clause.get("attr", "")))
        attr = _ATTR_ALIAS.get(attr, attr)
        op = str(clause.get("op", "")).strip().lower()
        op = _OP_ALIAS.get(op, _OP_ALIAS.get(slug(op), op))
        value = clause.get("value")
        if isinstance(value, list) and len(value) == 1 and is_macro(value[0]):
            value = value[0]
        if op == "has" and isinstance(value, list) and len(value) > 1:
            op = "has_all"
            readings.append("'has' with several conditions read as 'has all of'")
        if op in LIST_OPS and op != "between" and not isinstance(value, list) \
                and not is_macro(value):
            value = [value]
        if op not in LIST_OPS and isinstance(value, list) and len(value) == 1:
            value = value[0]
        spec = cat.attrs.get(attr)
        if spec and not is_macro(value):
            if isinstance(value, list):
                value = [_clean(cat, attr, spec.kind, v, readings) for v in value]
            else:
                value = _clean(cat, attr, spec.kind, value, readings)
        out.append({"attr": attr, "op": op, "value": value})
    return out, readings


def _in_domain(spec, v):
    if spec.kind in ("int", "float"):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
        return spec.lo <= v <= spec.hi
    if spec.kind in ("enum", "set"):
        return isinstance(v, str) and v in spec.values
    return False


def _parse_date(v):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def validate(filt, cat: Catalog) -> list[Issue]:
    """Structural and value checks on a resolved filter."""
    issues = []
    for i, cl in enumerate(filt):
        def err(msg):
            issues.append(Issue("validate", ERROR, msg, i))

        if not isinstance(cl, dict):
            err("not an {attr, op, value} clause")
            continue
        if "unresolved" in cl:
            continue
        attr, op, value = cl.get("attr"), cl.get("op"), cl.get("value")
        spec = cat.attrs.get(attr)
        if spec is None:
            err(f"unknown attribute '{attr}'")
            continue
        if op not in OPS[spec.kind]:
            err(f"operator '{op}' does not apply to {spec.label}")
            continue
        if op in LIST_OPS:
            if not isinstance(value, list) or not value:
                err(f"'{op}' needs a list of values")
                continue
            if op == "between" and len(value) != 2:
                err("'between' needs exactly two values")
                continue
            values = value
        else:
            if isinstance(value, list):
                err(f"'{op}' takes a single value")
                continue
            values = [value]

        if spec.kind == "date":
            parsed = [_parse_date(v) for v in values]
            bad = [v for v, d in zip(values, parsed) if d is None]
            if bad:
                err(f"not a date (YYYY-MM-DD): {', '.join(map(str, bad))}")
                continue
            lo, hi = date.fromisoformat(DATA_START), date.fromisoformat(DATA_END)
            outside = [str(d) for d in parsed if not lo <= d <= hi]
            if outside:
                issues.append(Issue("validate", WARNING,
                                    f"{', '.join(outside)} is outside the data "
                                    f"({DATA_START} to {DATA_END})", i))
            if op == "between" and parsed[0] > parsed[1]:
                err(f"range is reversed ({values[0]} after {values[1]})")
            continue

        bad = [v for v in values if not _in_domain(spec, v)]
        if bad:
            if spec.kind == "set":
                err(", ".join(f"'{v}'" for v in bad) + " is not a coded condition in this "
                    "catalog")
            elif spec.kind == "enum":
                err(", ".join(f"'{v}'" for v in bad) + f" is not a known {spec.label}")
            else:
                err(f"{', '.join(map(str, bad))} is outside {spec.label} "
                    f"({spec.lo} to {spec.hi})")
            continue
        if op == "between" and values[0] > values[1]:
            err(f"range is reversed ({values[0]} > {values[1]})")
    return issues


def _literal(v, kind):
    if isinstance(v, list):
        return "[" + ", ".join(_literal(x, kind) for x in v) + "]"
    if kind == "date":
        return f"DATE '{v}'"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return repr(v)


def compile_where(filt, cat: Catalog):
    """Valid resolved filter -> (readable SQL, parameterised SQL, params)."""
    shown, parts, params = [], [], []
    for cl in filt:
        spec = cat.attrs[cl["attr"]]
        col = "conditions" if spec.kind == "set" else spec.key
        op, v = cl["op"], cl["value"]
        ph = "CAST(? AS DATE)" if spec.kind == "date" else "?"
        lit = lambda x: _literal(x, spec.kind)
        if op == "between":
            parts.append(f"{col} BETWEEN {ph} AND {ph}")
            shown.append(f"{col} BETWEEN {lit(v[0])} AND {lit(v[1])}")
            params += v
        elif op in _SQL_OP:
            parts.append(f"{col} {_SQL_OP[op]} {ph}")
            shown.append(f"{col} {_SQL_OP[op]} {lit(v)}")
            params.append(v)
        elif op in ("in", "not_in"):
            neg = "NOT " if op == "not_in" else ""
            parts.append(f"{col} {neg}IN ({', '.join([ph] * len(v))})")
            shown.append(f"{col} {neg}IN ({', '.join(lit(x) for x in v)})")
            params += v
        elif op == "has":
            parts.append(f"list_contains({col}, ?)")
            shown.append(f"list_contains({col}, {lit(v)})")
            params.append(v)
        else:
            fn = "list_has_all" if op == "has_all" else "list_has_any"
            neg = "NOT " if op == "has_none" else ""
            parts.append(f"{neg}{fn}({col}, ?::VARCHAR[])")
            shown.append(f"{neg}{fn}({col}, {lit(v)})")
            params.append(list(v))
    if not parts:
        return "TRUE", "TRUE", []
    return "\n  AND ".join(shown), " AND ".join(parts), params


def _show(attr, v, cat):
    if isinstance(v, float):
        return f"{v:g}"
    return cat.label(attr, v)


def render(cl, cat: Catalog) -> str:
    """One clause in plain words, for the panel."""
    if not isinstance(cl, dict):
        return str(cl)
    spec = cat.attrs.get(cl.get("attr"))
    label = spec.label if spec else str(cl.get("attr"))
    if "unresolved" in cl:
        return f"{label}: {cl['unresolved']} (not resolved)"
    op, v = cl.get("op"), cl.get("value")
    attr = cl.get("attr")
    unit = f" {spec.unit}" if spec and spec.unit and spec.kind in ("int", "float") else ""
    names = lambda xs: ", ".join(cat.label(attr, x) for x in xs)
    if op == "between" and isinstance(v, list) and len(v) == 2:
        return f"{label} between {_show(attr, v[0], cat)} and {_show(attr, v[1], cat)}{unit}"
    if op in _SHOW_OP:
        return f"{label} {_SHOW_OP[op]} {_show(attr, v, cat)}{unit}"
    if op in ("in", "not_in") and isinstance(v, list):
        word = "one of" if op == "in" else "none of"
        return f"{label} is {word} {names(v)}{unit}"
    if op == "has":
        return f"has {cat.label('condition', v)}"
    words = {"has_any": "has any of", "has_all": "has all of", "has_none": "has none of"}
    if op in words and isinstance(v, list):
        return f"{words[op]} {names(v)}"
    return f"{label} {op} {v}"
