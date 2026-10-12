# Cohort Scout

Clinicians describe the patients they need in plain language, in any language. An open model
running on the hospital's own AMD GPU drafts a filter, deterministic checks mark every clause
that does not add up, and nothing runs until the clinician has read it and pressed Run.

Built for the AMD Developer Hackathon: ACT III, track 2 (Health and Wellbeing).

## The problem

Finding a cohort ("diabetic women over 65 in the North-West, admitted last year") means
either waiting for an analyst or fighting a filter panel with dozens of attributes and hundreds
of codes. A language model can write the query in a second, but a query that looks right and
selects the wrong patients is worse than no query, and nothing on the screen tells the two
apart.

## How it works

1. The request goes to an open model served by vLLM on an AMD Instinct GPU. The model returns
   a small JSON filter (`attr`, `op`, `value` clauses), never SQL.
2. Group shortcuts (`chapter:circulatory`, `area:sud`) are expanded from the catalog, and the
   expansion is shown, so a reader checks "Sud = these 6 regions" rather than a list of codes.
3. The checks below run on the request and the filter. Errors block the query; warnings and
   assumptions are shown next to the clause they concern.
4. The clinician edits any clause. Every edit reruns the checks.
5. The filter is compiled to parameterised SQL and runs on DuckDB.

| Check | What it catches | Level |
|---|---|---|
| validate | values that do not exist (`long_covid` when the catalog has no such code), wrong operators, reversed ranges | error |
| unresolved | periods or distances nothing in the data can define (`event:heatwave_2023`, `near(Milano, 30)`) | error |
| refusal | an empty filter, which would silently select everyone | error |
| coverage | a part of the request with no clause, or a clause the request never asked for | warning |
| near-set | a hand-written list that is almost a group: 6 of the 7 circulatory conditions, or one region when the request said "the South" | warning |
| conjunction | "diabetes and asthma" answered with "any of", or the reverse | warning |
| provenance | numbers and dates nobody wrote: `age >= 65` for "elderly", June to August for "the summer heatwave", a whole region for a city | assumption |

All checks are plain code: no second model judges the first one.

## Why a local model

Health records should not leave the hospital. The whole stack (model, checks, database) runs on
one machine the hospital controls. On AMD Developer Cloud a single MI300X (192 GB) serves a
70B-class model in bf16 with room for the KV cache, and the same containers run on an on-premise
Instinct server.

## Run it

Local development, with any OpenAI-compatible endpoint (vLLM, LM Studio, Ollama):

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip
cp .env.example .env                             # set LLM_BASE_URL and LLM_MODEL
.venv/bin/python -m uvicorn cohort.api:app --port 8080
```

Open http://localhost:8080. The synthetic database (200,000 admissions) is built on first
start in about a second. Without a model the filter can still be written by hand.

With Docker:

```bash
docker compose up --build
```

On an AMD GPU machine, model server included: see [deploy/amd](deploy/amd/README.md).

## Evaluation

`eval/gold.py` holds 23 requests in English and Italian, each with a reference filter. Four of
them are probes whose right outcome is a visible flag.

```bash
python -m eval.run draft --out results/qwen72b.jsonl    # calls the model
python -m eval.run score results/qwen72b.jsonl          # offline, reruns the checks
```

The score reports exact matches and, more importantly, the residual: wrong filters that no
check marked. Re-scoring is free, so a change to a check is measured on recorded runs without
calling the model again.

Results on AMD hardware: to be added.

## Data

Every patient is synthetic (`cohort/data.py`, fixed seed). Conditions are coded by ICD-10
chapter; geography uses the 20 Italian regions and the ISTAT macro-areas. Both live in
`catalog/` as CSV files, so another country or coding system is a matter of replacing them.

## Tests

```bash
python -m pytest
```

Among other things the suite checks that every reference filter passes all checks without a
single note in both languages, and that every probe is flagged.

## Layout

```
catalog/   conditions (ICD-10), chapters, regions, areas, cities
cohort/    catalog loading, filter language, checks, model client, data, API
web/       single-page interface, no build step
eval/      reference requests and scorer
deploy/    AMD deployment notes
```

## License

MIT
