"""Group shortcuts: the model writes chapter:<key> or area:<key>, the catalog expands it.

A shortcut either resolves or is reported. Shortcuts with nothing in the data to resolve them
(event:<name>, near(<place>, <km>)) are kept and marked, so that a guessed period or a guessed
list of regions never reaches the query silently.
"""
import re

from .catalog import Catalog
from .text import slug

MACRO = re.compile(r"^\s*(chapter|category|area|event)\s*:\s*(.+?)\s*$", re.I)
NEAR = re.compile(r"^\s*near\s*\(\s*([^,]+?)\s*,\s*([0-9.]+)\s*(?:km)?\s*\)\s*$", re.I)
_KIND = {"category": "chapter"}
_ATTR_OF = {"chapter": "condition", "area": "region"}

UNRESOLVED = object()


def is_macro(value) -> bool:
    return isinstance(value, str) and bool(MACRO.match(value) or NEAR.match(value))


def macro_key(value: str) -> str:
    near = NEAR.match(value)
    if near:
        return f"near:{slug(near.group(1))}:{float(near.group(2)):g}"
    m = MACRO.match(value)
    kind = _KIND.get(m.group(1).lower(), m.group(1).lower())
    return f"{kind}:{slug(m.group(2))}"


def expand(attr: str, value, cat: Catalog):
    """-> (members, line) | (UNRESOLVED, reason) | (None, None) when value is not a shortcut."""
    if not is_macro(value):
        return None, None
    near = NEAR.match(value)
    if near:
        return UNRESOLVED, (f"{value}: the data records the region of residence only, so a "
                            f"distance cannot be computed. Pick the regions by hand.")
    m = MACRO.match(value)
    kind = _KIND.get(m.group(1).lower(), m.group(1).lower())
    key = slug(m.group(2))
    if kind == "event":
        return UNRESOLVED, (f"{value}: nothing in the data defines this period. Enter the "
                            f"dates by hand.")
    if _ATTR_OF[kind] != attr:
        return UNRESOLVED, f"{value}: a {kind} shortcut cannot be used on {attr}."
    groups = cat.chapters if kind == "chapter" else cat.areas
    if key not in groups:
        return UNRESOLVED, f"{value}: no such {kind}. Known: {', '.join(groups)}."
    group = groups[key]
    members = list(group["members"])
    if kind == "chapter":
        names = ", ".join(cat.conditions[k]["name"] for k in members)
        return members, (f"chapter:{key} = {group['name']} ({group['icd10']}), "
                         f"{len(members)} conditions: {names}")
    names = ", ".join(cat.regions[k]["name"] for k in members)
    return members, f"area:{key} = {group['name']}, {len(members)} regions: {names}"


def resolve(filt: list, cat: Catalog):
    """Expand every shortcut -> (filter, trace lines, [(clause index, reason)])."""
    out, trace, unresolved = [], [], []
    for i, clause in enumerate(filt):
        if not isinstance(clause, dict):
            out.append(clause)
            continue
        members, line = expand(clause.get("attr"), clause.get("value"), cat)
        if members is None:
            out.append(clause)
        elif members is UNRESOLVED:
            unresolved.append((i, line))
            out.append({**clause, "value": None, "unresolved": clause["value"]})
        else:
            trace.append(line)
            out.append({**clause, "value": members, "shortcut": clause["value"]})
    return out, trace, unresolved
