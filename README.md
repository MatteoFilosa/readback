# Cohort Scout

Clinicians describe the patients they need in plain language, in any language. An open model on
AMD GPUs fills in the search criteria, deterministic checks mark every criterion that does not
add up, and nothing runs until the clinician has read them and pressed Run.

Built for the AMD Developer Hackathon: ACT III, track 2 (Health and Wellbeing).

## The problem

Finding a cohort ("diabetic women over 65 in the North-West, admitted last year") means
either waiting for an analyst or fighting a filter panel with dozens of attributes and hundreds
of codes. A language model can write the query in a second, but a query that looks right and
selects the wrong patients is worse than no query, and nothing on the screen tells the two
apart.

## How it works

1. The request goes to an open model on AMD GPUs. The model returns a small JSON filter
   (`attr`, `op`, `value` clauses), never SQL.
2. Group shortcuts (`chapter:circulatory`, `area:sud`) are expanded from the catalog, and the
   expansion is shown, so a reader checks "Sud = these 6 regions" rather than a list of codes.
3. The criteria appear in a fixed form. Every attribute is listed; whatever the request did not
   mention stays "Any". Each criterion shows the words of the request it rests on, or "not in
   the request", and the request is echoed with those words highlighted.
4. The checks below run on the request and the filter. Errors block the query; warnings and
   assumptions are shown on the criterion they concern, and each attribute carries a state:
   from the request, assumed, check, fix before Run, or mentioned but not filtered.
5. The clinician edits any criterion. Every edit reruns the checks.
6. On Run the filter is compiled to parameterised SQL on DuckDB. The result shows how each
   criterion narrows the cohort, so a clause that removes no one, or everyone, stands out.

| Check | What it catches | Level |
|---|---|---|
| validate | values that do not exist (`long_covid` when the catalog has no such code), wrong operators, reversed ranges | error |
| unresolved | periods or distances nothing in the data can define (`event:heatwave_2023`, `near(Milano, 30)`) | error |
| refusal | an empty filter, which would silently select everyone | error |
| contradiction | criteria no patient can meet together: admitted on 1 January and on 31 December | error |
| coverage | a part of the request with no clause, or a clause the request never asked for | warning |
| near-set | a hand-written list that is almost a group: 6 of the 7 circulatory conditions, or one region when the request said "the South" | warning |
| conjunction | "diabetes and asthma" answered with "any of", or "Crohn's or colitis" split into clauses that must all hold | warning |
| value | a sex or smoking status the request names, answered with another one or with extra ones: "ex fumatori" read as current smokers | warning |
| provenance | numbers and dates nobody wrote: `age >= 65` for "elderly", June to August for "the summer heatwave", 1 January for "in 2024", a whole region for a city | assumption |

All checks are plain code: no second model judges the first one.

## Where the model runs

The demo calls AMD Token Factory: free, shared, OpenAI-compatible endpoints for open models on
AMD GPUs. They suit synthetic data and nothing else: their terms rule out health data, and they
keep prompts for about two days. The model never sees a patient record in any case. It
receives the request and the catalog; the query runs on the app's own DuckDB.

A hospital would serve the same open weights itself. `docker-compose.amd.yml` runs vLLM on an
AMD Instinct GPU next to the app; a single MI300X (192 GB) holds a 70B-class model in bf16.
That setup is written but has not been run on the hardware yet.

## Run it

Local development, with any OpenAI-compatible endpoint. The defaults in `.env.example` point
to AMD Token Factory, free shared model endpoints on AMD GPUs; put the team key in
`LLM_API_KEY`.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip
cp .env.example .env.local                       # set LLM_API_KEY
.venv/bin/python -m uvicorn cohort.api:app --port 8080 --env-file .env.local
```

Open http://localhost:8080. The synthetic database (200,000 admissions) is built on first
start in about a second. Without a model the filter can still be written by hand.

The Token Factory key is shared by the whole team, and so are its limits (20 requests per
minute, a daily spend cap; `GET /v1/usage` shows what is left). Run the evaluation with
`--rpm` low enough to leave room for the others.

With Docker:

```bash
docker compose up --build
```

On an AMD GPU machine, model server included: see [deploy/amd](deploy/amd/README.md).

## Evaluation

`eval/gold.py` holds 23 requests in English and Italian, each with a reference filter. Four of
them are probes whose right outcome is a visible flag.

```bash
python -m eval.run draft --env-file .env.local --out results/run.jsonl   # calls the model
python -m eval.run score results/run.jsonl                               # offline
```

The score reports exact matches and, more importantly, the residual: wrong filters that no
check marked. Re-scoring is free, so a change to a check is measured on recorded runs without
calling the model again.

Results on AMD Token Factory, 13 October 2026, 46 drafts per model (23 requests in English and
in Italian):

| Model | Exact (EN / IT) | Wrong and unmarked | Median / p90 latency |
|---|---|---|---|
| Qwen3.8-27B, reasoning low | 23 / 22 | 0 of 46 | 9.9 / 21.6 s |
| DeepSeek-V4-Flash | 22 / 22 | 0 of 46 | 4.7 / 19.4 s |
| MiMo-V2.6-Flash, reasoning none | 21 / 22 | 0 of 46 | 4.0 / 5.8 s |
| MiniCPM-V-4.7-35B-A3B | 21 / 20 | 0 of 46 | 5.3 / 9.5 s |
| Qwen3.8-Flash-Next, reasoning none | 20 / 20 | 0 of 46 | 5.5 / 12.5 s |
| MiniCPM5-2B | 14 / 11 | 0 of 46 | 2.0 / 10.4 s |

Zero of 46 has a 95% upper bound of 7.7%. The 2B model was the useful one: its 21 wrong drafts
exposed three gaps (two dates that cannot both hold, "or" split into separate clauses, "ex
smokers" read as smokers), now covered by the contradiction, conjunction and value checks.
These figures come from the set the checks were tuned on; a held-out set is the next step.

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
