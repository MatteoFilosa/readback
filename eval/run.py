"""Run the gold set against a model, or re-score a recorded run.

  python -m eval.run draft --out results/run.jsonl      # calls the model, one line per request
  python -m eval.run score results/run.jsonl            # recomputes scores and checks offline
  python -m eval.run examples --env-file .env.local     # drafts the UI replays if the model is down

Scoring compares clause sets after both sides are normalised and resolved, so "age > 65" and
"age >= 66", or a group shortcut and its expanded list, count as the same filter.
"""
import argparse
import json
import math
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from cohort import llm
from cohort.catalog import get_catalog
from cohort.checks import review
from cohort.filters import normalize
from cohort.resolve import NEAR, resolve

from .gold import GOLD, LANGS

TODAY = date(2026, 10, 12)
ROOT = Path(__file__).resolve().parent.parent


def _bounds(spec, op, v):
    step = 1 if spec.kind == "int" else 0
    if spec.kind == "date":
        d = date.fromisoformat
        lo, hi = d(spec.lo), d(spec.hi)
        if op == "between":
            return d(v[0]), d(v[1])
        x = d(v)
        return {"ge": (x, hi), "gt": (x + timedelta(days=1), hi), "le": (lo, x),
                "lt": (lo, x - timedelta(days=1)), "eq": (x, x)}[op]
    if op == "between":
        return v[0], v[1]
    if op == "in" and spec.kind == "int" and sorted(v) == list(range(min(v), max(v) + 1)):
        return min(v), max(v)
    return {"ge": (v, spec.hi), "gt": (v + step, spec.hi), "le": (spec.lo, v),
            "lt": (spec.lo, v - step), "eq": (v, v)}.get(op)


def canonical(filt, cat):
    """Filter -> frozenset of comparable clause keys, or None if it cannot be read."""
    norm, _ = normalize(filt, cat)
    resolved, _, _ = resolve(norm, cat)
    ranges, keys, has = {}, set(), []
    for cl in resolved:
        if not isinstance(cl, dict) or cl.get("attr") not in cat.attrs:
            keys.add(("invalid", json.dumps(cl, sort_keys=True, default=str)))
            continue
        attr, op, v = cl["attr"], cl["op"], cl.get("value")
        spec = cat.attrs[attr]
        if "unresolved" in cl:
            kind = "near" if NEAR.match(str(cl["unresolved"])) else \
                str(cl["unresolved"]).split(":")[0].lower()
            keys.add((attr, "unresolved", kind))
            continue
        if spec.kind in ("int", "float", "date"):
            try:
                b = _bounds(spec, op, v)
            except (TypeError, ValueError, KeyError, IndexError):
                b = None
            if b is None:
                keys.add((attr, op, json.dumps(v, default=str)))
                continue
            lo, hi = ranges.get(attr, (b[0], b[1]))
            ranges[attr] = (max(lo, b[0]), min(hi, b[1]))
            continue
        if op == "has" or (op in ("has_any", "has_all") and isinstance(v, list) and len(v) == 1):
            has.append(v[0] if isinstance(v, list) else v)
            continue
        if op == "eq":
            op, v = "in", [v]
        if op == "ne":
            op, v = "not_in", [v]
        vk = tuple(sorted(map(str, v))) if isinstance(v, list) else v
        keys.add((attr, op, vk))
    if len(has) == 1:
        keys.add(("condition", "has", has[0]))
    elif has:
        keys.add(("condition", "has_all", tuple(sorted(has))))
    for attr, (lo, hi) in ranges.items():
        keys.add((attr, "range", str(lo), str(hi)))
    return frozenset(keys)


def score(pred, gold, cat) -> str:
    p, g = canonical(pred, cat), canonical(gold, cat)
    if p == g:
        return "exact"
    return "partial" if p & g else "miss"


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def draft_run(out_path, langs, rpm):
    cat = get_catalog()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    os.environ.setdefault("LLM_MAX_WAIT", "90")
    model = llm.served_model()
    gap, last = 60 / rpm if rpm else 0, 0.0
    with open(out_path, "a", encoding="utf-8") as f:
        for item in GOLD:
            for lang in langs:
                time.sleep(max(0.0, last + gap - time.monotonic()))
                last = time.monotonic()
                out = llm.draft(item[lang], cat, TODAY)
                f.write(json.dumps({"model": out["model"] or model, "lang": lang, "id": item["id"],
                                    "request": item[lang], "pred": out["filter"],
                                    "note": out["note"], "ms": out["ms"],
                                    "tokens": out["tokens"], "error": out["error"],
                                    "raw": out["raw"]}, ensure_ascii=False) + "\n")
                print(f"{lang} {item['id']:<30} {out['ms']:>6} ms"
                      + (f"  ERROR {out['error']}" if out["error"] else ""))


def ui_examples() -> list[str]:
    src = (ROOT / "web" / "app.js").read_text("utf-8")
    start = src.index("const EXAMPLES")
    block = src[start:src.index("};", start)]
    return [json.loads(f'"{m}"') for m in re.findall(r'^\s+"(.+)",\s*$', block, re.M)]


def examples_run(out_path, rpm):
    cat = get_catalog()
    os.environ.setdefault("LLM_MAX_WAIT", "90")
    old = {}
    if os.path.exists(out_path):
        old = {r["request"]: r for r in json.load(open(out_path, encoding="utf-8"))}
    rows, gap, last = [], 60 / rpm if rpm else 0, 0.0
    for request in ui_examples():
        time.sleep(max(0.0, last + gap - time.monotonic()))
        last = time.monotonic()
        out = llm.draft(request, cat)
        if out["error"]:
            print(f"ERROR {request}: {out['error']}")
            if request in old:
                rows.append(old[request])
            continue
        rows.append({"request": request, "model": out["model"], "date": date.today().isoformat(),
                     "filter": out["filter"], "note": out["note"]})
        print(f"{out['ms']:>6} ms  {request}")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
        f.write("\n")


def score_run(path):
    cat = get_catalog()
    gold = {g["id"]: g for g in GOLD}
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    groups = {}
    for r in rows:
        groups.setdefault((r["model"], r["lang"]), []).append(r)
    for (model, lang), rs in sorted(groups.items()):
        tally = {"exact": 0, "partial": 0, "miss": 0}
        marked_wrong = residual = false_alarm = 0
        by_check, silent = {}, []
        for r in rs:
            g = gold[r["id"]]
            rep = review(r["request"], r["pred"], cat, TODAY)
            s = score(r["pred"], g["filter"], cat)
            tally[s] += 1
            marked = bool(rep.issues)
            for c in {i.check for i in rep.issues}:
                by_check[c] = by_check.get(c, 0) + 1
            if s != "exact" and marked:
                marked_wrong += 1
            if s != "exact" and not marked:
                residual += 1
                silent.append((r["id"], r["pred"]))
            if s == "exact" and marked and not g.get("probe"):
                false_alarm += 1
        n = len(rs)
        wrong = n - tally["exact"]
        lo, hi = wilson(residual, n)
        print(f"\n{model} [{lang}] n={n}")
        print(f"  exact {tally['exact']}/{n}  partial {tally['partial']}  miss {tally['miss']}")
        print(f"  wrong answers marked by a check: {marked_wrong}/{wrong}")
        print(f"  residual (wrong and unmarked): {residual}/{n}  95% CI {lo:.2f}-{hi:.2f}")
        print(f"  notes on exact non-probe answers: {false_alarm}")
        print(f"  checks fired: {dict(sorted(by_check.items()))}")
        for rid, pred in silent:
            print(f"    silent: {rid}: {json.dumps(pred, ensure_ascii=False)}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--out", required=True)
    d.add_argument("--langs", default=",".join(LANGS))
    d.add_argument("--env-file", help="KEY=VALUE file, e.g. .env.local")
    d.add_argument("--model", help="overrides LLM_MODEL")
    d.add_argument("--reasoning", help="overrides LLM_REASONING (reasoning_effort)")
    # Shared endpoints throttle per key; 0 disables pacing for a private vLLM.
    d.add_argument("--rpm", type=float, default=15)
    s = sub.add_parser("score")
    s.add_argument("path")
    e = sub.add_parser("examples")
    e.add_argument("--out", default=str(ROOT / "cohort" / "saved_drafts.json"))
    e.add_argument("--env-file", help="KEY=VALUE file, e.g. .env.local")
    e.add_argument("--rpm", type=float, default=15)
    args = ap.parse_args(argv)
    if getattr(args, "env_file", None):
        load_dotenv(args.env_file, override=True)
    if args.cmd == "examples":
        examples_run(args.out, args.rpm)
    elif args.cmd == "draft":
        if args.model:
            os.environ["LLM_MODEL"] = args.model
        if args.reasoning is not None:
            os.environ["LLM_REASONING"] = args.reasoning
        draft_run(args.out, [x.strip() for x in args.langs.split(",") if x.strip()], args.rpm)
    else:
        score_run(args.path)


if __name__ == "__main__":
    sys.exit(main())
