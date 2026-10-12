"""Client for any OpenAI-compatible chat endpoint (vLLM, LM Studio, Ollama, llama.cpp)."""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import date

from .catalog import OPS, Catalog, get_catalog


def settings() -> dict:
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1").rstrip("/"),
        "model": os.environ.get("LLM_MODEL", ""),
        "api_key": os.environ.get("LLM_API_KEY", "EMPTY"),
        "timeout": float(os.environ.get("LLM_TIMEOUT", "90")),
        "json_mode": os.environ.get("LLM_JSON", "0") == "1",
        "hardware": os.environ.get("LLM_HARDWARE", ""),
    }


def _attr_line(a):
    if a.kind in ("int", "float"):
        dom = f"{a.kind} {a.lo:g}..{a.hi:g}" + (f" {a.unit}" if a.unit else "")
    elif a.kind == "date":
        dom = f"date YYYY-MM-DD, {a.lo}..{a.hi}"
    elif a.key == "region":
        dom = "enum, see Regions"
    elif a.kind == "enum":
        dom = "enum: " + ", ".join(a.values)
    else:
        dom = "set of condition keys, see Conditions"
    note = f" ({a.note})" if a.note else ""
    return f"  {a.key}: {dom}{note}"


def system_prompt(cat: Catalog, today: date) -> str:
    attrs = "\n".join(_attr_line(a) for a in cat.attrs.values())
    conditions = "\n".join(f"  {k} ({c['icd10']})" for k, c in cat.conditions.items())
    chapters = ", ".join(cat.chapters)
    areas = ", ".join(cat.areas)
    regions = ", ".join(cat.regions)
    ops = "; ".join(f"{k}: {', '.join(v)}" for k, v in OPS.items())
    return f"""You translate a clinician's request into a filter over one table of hospital \
admissions, one row per admission. The request can be in any language. Keys are \
identifiers: copy them exactly as listed, never translate them.

Attributes:
{attrs}

Operators by type: {ops}.
between, in, not_in, has_any, has_all and has_none take a list; between is inclusive. \
Clauses are combined with AND.

Regions: {regions}

Conditions (key and ICD-10 codes):
{conditions}

Groups. Write the group, never the list of its members:
  chapter:<key> for every condition of an ICD-10 chapter: {chapters}
  area:<key> for every region of an area: {areas}

Do not guess. If the request names a period the data cannot define (an event, a season with \
no dates), write event:<short_name> as the value. If it names a distance from a place, write \
near(<place>, <km>) as the value of region. If it needs a condition or attribute not listed, \
leave that part out and say so in "note".

Today is {today.isoformat()}.

Reply with JSON only, in this shape:
{{"filter": [{{"attr": "...", "op": "...", "value": ...}}], "note": "..."}}

Example: "women over 70 with heart failure" ->
{{"filter": [{{"attr": "sex", "op": "eq", "value": "female"}}, \
{{"attr": "age", "op": "gt", "value": 70}}, \
{{"attr": "condition", "op": "has", "value": "heart_failure"}}], "note": ""}}

Example: "pazienti con una malattia respiratoria residenti nelle isole" ->
{{"filter": [{{"attr": "condition", "op": "has_any", "value": "chapter:respiratory"}}, \
{{"attr": "region", "op": "in", "value": "area:isole"}}], "note": ""}}"""


def _first_object(text: str) -> dict:
    start = text.find("{")
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object in the reply")


def _post(url, body, cfg):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"})
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
        return json.load(r)


def served_model(cfg=None) -> str:
    """LLM_MODEL, or the first model the endpoint lists (vLLM serves exactly one)."""
    cfg = cfg or settings()
    if cfg["model"]:
        return cfg["model"]
    req = urllib.request.Request(f"{cfg['base_url']}/models",
                                 headers={"Authorization": f"Bearer {cfg['api_key']}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["data"][0]["id"]


def draft(request: str, cat: Catalog | None = None, today: date | None = None) -> dict:
    """Request -> {filter, note, model, ms, tokens, error, raw}. Never raises."""
    cat = cat or get_catalog()
    cfg = settings()
    out = {"filter": [], "note": "", "model": cfg["model"], "ms": None,
           "tokens": [None, None], "error": None, "raw": ""}
    t0 = time.perf_counter()
    try:
        out["model"] = served_model(cfg)
        body = {
            "model": out["model"],
            "temperature": 0,
            "max_tokens": 600,
            "messages": [{"role": "system", "content": system_prompt(cat, today or date.today())},
                         {"role": "user", "content": request}],
        }
        if cfg["json_mode"]:
            body["response_format"] = {"type": "json_object"}
        reply = _post(f"{cfg['base_url']}/chat/completions", body, cfg)
        out["raw"] = reply["choices"][0]["message"]["content"] or ""
        usage = reply.get("usage") or {}
        out["tokens"] = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
        parsed = _first_object(out["raw"])
        out["filter"] = parsed.get("filter", []) if isinstance(parsed, dict) else []
        out["note"] = str(parsed.get("note") or "") if isinstance(parsed, dict) else ""
    except urllib.error.HTTPError as e:
        detail = e.read(500).decode("utf-8", "replace")
        out["error"] = f"model endpoint returned HTTP {e.code}: {detail}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        out["error"] = f"model endpoint unreachable at {cfg['base_url']} ({e})"
    except (ValueError, KeyError, IndexError) as e:
        out["error"] = f"unreadable model reply: {e}"
    out["ms"] = round((time.perf_counter() - t0) * 1000)
    return out
