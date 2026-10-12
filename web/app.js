const EXAMPLES = [
  "Patients aged 40 to 60 with diabetes",
  "Pazienti con diabete e ipertensione residenti nel Nord-Ovest",
  "Very sick elderly patients",
  "Patients admitted during the 2023 summer heatwave",
  "Pazienti in codice rosso con febbre sopra i 39 gradi",
  "Asthma patients within 30 km of Milan",
  "Patients with long COVID",
  "Patients de plus de 70 ans avec une maladie cardiovasculaire",
];
const TAGS = {
  validate: "invalid", unresolved: "unresolved", refusal: "empty", coverage: "coverage",
  near_set: "near-set", conjunction: "and / or", provenance: "source",
};
const LIST_OPS = new Set(["between", "in", "not_in", "has_any", "has_all", "has_none"]);
const OP_LABEL = {
  between: "between", lt: "<", le: "≤", gt: ">", ge: "≥", eq: "is", ne: "is not",
  in: "is one of", not_in: "is none of", has: "has", has_any: "has any of",
  has_all: "has all of", has_none: "has none of",
};

const $ = (id) => document.getElementById(id);
const state = { catalog: null, meta: null, filter: [], drafted: null, draftId: null, report: null };
let reviewTimer = null;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(res.statusText), { data });
  return data;
}

const attr = (key) => state.catalog.attrs.find((a) => a.key === key);
const fmt = (n) => Number(n).toLocaleString("en-US");

function valueToText(v) {
  if (Array.isArray(v)) return v.join(", ");
  return v ?? "";
}

function textToValue(text, a, op) {
  const parse = (s) => {
    s = s.trim();
    if (!a || !["int", "float"].includes(a.kind) || s === "") return s;
    const n = Number(s.replace(",", "."));
    return Number.isNaN(n) ? s : n;
  };
  const t = text.trim();
  if (/^(chapter|area|event|category)\s*:/i.test(t) || /^near\s*\(/i.test(t)) return t;
  if (LIST_OPS.has(op)) return t === "" ? [] : t.split(/\s*[,;]\s*/).map(parse);
  return parse(t);
}

function datalistFor(a) {
  if (!a) return "";
  if (a.key === "condition") return "dl-condition";
  if (a.key === "region") return "dl-region";
  if (a.key === "sex") return "dl-sex";
  if (a.key === "smoking") return "dl-smoking";
  return "";
}

function fillDatalists() {
  const c = state.catalog;
  const opts = (items) => items.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
  $("dl-condition").innerHTML = opts([
    ...c.chapters.map((x) => [`chapter:${x.key}`, `${x.name} (${x.icd10})`]),
    ...c.conditions.map((x) => [x.key, `${x.name} (${x.icd10})`]),
  ]);
  $("dl-region").innerHTML = opts([
    ...c.areas.map((x) => [`area:${x.key}`, x.name]),
    ...c.regions.map((x) => [x.key, x.name]),
  ]);
  $("dl-sex").innerHTML = opts(attr("sex").values.map((v) => [v, v]));
  $("dl-smoking").innerHTML = opts(attr("smoking").values.map((v) => [v, v]));
}

function issueHtml(i) {
  return `<div class="issue ${i.level}"><span class="tag">${esc(TAGS[i.check] || i.check)}</span>` +
    `<span class="msg">${esc(i.message)}</span></div>`;
}

function renderClauses() {
  const box = $("clauses");
  box.innerHTML = "";
  state.filter.forEach((cl, idx) => {
    const a = attr(cl.attr);
    const row = document.createElement("div");
    row.className = "clause";
    row.dataset.idx = idx;
    const attrOpts = state.catalog.attrs.map((x) =>
      `<option value="${x.key}" ${x.key === cl.attr ? "selected" : ""}>${esc(x.label)}</option>`).join("");
    const ops = a ? a.ops : [cl.op];
    const opOpts = ops.map((o) =>
      `<option value="${o}" ${o === cl.op ? "selected" : ""}>${esc(OP_LABEL[o] || o)}</option>`).join("");
    const unknownAttr = a ? "" : `<option value="${esc(cl.attr)}" selected>${esc(cl.attr)}</option>`;
    row.innerHTML = `
      <div class="clause-fields">
        <select data-f="attr" aria-label="Attribute">${unknownAttr}${attrOpts}</select>
        <select data-f="op" aria-label="Operator">${opOpts}</select>
        <input data-f="value" aria-label="Value" list="${datalistFor(a)}" value="${esc(valueToText(cl.value))}"
               placeholder="${a && LIST_OPS.has(cl.op) ? "values, separated by commas" : "value"}">
        <button class="icon" data-f="remove" title="Remove clause" aria-label="Remove clause">✕</button>
      </div>
      <div class="readable"></div>
      <div class="clause-issues"></div>`;
    box.appendChild(row);
  });
}

function onClauseEvent(e) {
  const row = e.target.closest(".clause");
  if (!row) return;
  const idx = Number(row.dataset.idx);
  const f = e.target.dataset.f;
  const cl = state.filter[idx];
  if (f === "remove") {
    state.filter.splice(idx, 1);
    renderClauses();
  } else if (f === "attr") {
    const a = attr(e.target.value);
    state.filter[idx] = { attr: a.key, op: a.ops[0], value: LIST_OPS.has(a.ops[0]) ? [] : "" };
    renderClauses();
  } else if (f === "op") {
    cl.op = e.target.value;
    const text = row.querySelector('[data-f="value"]').value;
    cl.value = textToValue(text, attr(cl.attr), cl.op);
  } else if (f === "value") {
    cl.value = textToValue(e.target.value, attr(cl.attr), cl.op);
  } else {
    return;
  }
  scheduleReview();
}

function scheduleReview() {
  clearTimeout(reviewTimer);
  reviewTimer = setTimeout(async () => {
    const report = await api("/api/review", { request: $("request").value, filter: state.filter });
    showReport(report);
  }, 250);
}

function showReport(r) {
  state.report = r;
  const rows = [...document.querySelectorAll(".clause")];
  rows.forEach((row, idx) => {
    const own = r.issues.filter((i) => i.clause === idx);
    row.querySelector(".readable").textContent = r.readable[idx] || "";
    row.querySelector(".clause-issues").innerHTML = own.map(issueHtml).join("");
    row.classList.toggle("has-error", own.some((i) => i.level === "error"));
  });
  $("general-issues").innerHTML = r.issues.filter((i) => i.clause === null).map(issueHtml).join("");
  $("explain").innerHTML = r.explanation.map((x) => `<li>${esc(x)}</li>`).join("");
  $("explain-box").hidden = r.explanation.length === 0;
  $("sql").textContent = r.sql;
  $("sql-box").hidden = !r.sql;
  const errors = r.issues.filter((i) => i.level === "error").length;
  const others = r.issues.length - errors;
  $("run").disabled = !r.runnable;
  $("run").textContent = `Run on ${fmt(state.meta?.patients || 0)} admissions`;
  $("run-hint").textContent = errors
    ? `${errors} blocking issue${errors > 1 ? "s" : ""} to fix first`
    : others ? `${others} note${others > 1 ? "s" : ""} to read before running` : "No issues found";
}

async function draft() {
  const request = $("request").value.trim();
  if (!request) return $("request").focus();
  $("draft").disabled = true;
  $("draft-info").textContent = "Drafting…";
  try {
    const out = await api("/api/draft", { request });
    state.filter = out.filter;
    state.drafted = JSON.parse(JSON.stringify(out.filter));
    state.draftId = out.id;
    $("filter-card").hidden = false;
    $("note").hidden = !out.note;
    $("note").textContent = out.note ? `Model note: ${out.note}` : "";
    if (out.llm.error) {
      $("draft-info").textContent = `${out.llm.error}. You can still write the filter by hand.`;
    } else {
      $("draft-info").textContent =
        `Drafted by ${out.llm.model} in ${(out.llm.ms / 1000).toFixed(1)} s. Nothing runs until you press Run.`;
    }
    renderClauses();
    showReport(out);
  } catch (e) {
    $("draft-info").textContent = "The server did not answer.";
  } finally {
    $("draft").disabled = false;
  }
}

function startEmpty() {
  state.filter = [{ attr: "age", op: "ge", value: "" }];
  state.drafted = null;
  state.draftId = null;
  $("filter-card").hidden = false;
  $("note").hidden = true;
  renderClauses();
  scheduleReview();
}

function bars(el, items, total) {
  const max = Math.max(1, ...items.map((x) => x.n));
  el.innerHTML = items.map((x) => `
    <div class="bar"><span class="name" title="${esc(x.label)}">${esc(x.label)}</span>
      <span class="track"><span class="fill" style="width:${(100 * x.n / max).toFixed(1)}%"></span></span>
      <span class="n">${total ? (100 * x.n / total).toFixed(1) + "%" : fmt(x.n)}</span></div>`).join("");
}

async function run() {
  $("run").disabled = true;
  try {
    const out = await api("/api/run", {
      request: $("request").value, filter: state.filter, drafted: state.drafted, draft_id: state.draftId,
    });
    const r = out.result;
    const c = state.catalog;
    const condName = Object.fromEntries(c.conditions.map((x) => [x.key, x.name]));
    const regName = Object.fromEntries(c.regions.map((x) => [x.key, x.name]));
    $("placeholder").hidden = true;
    $("result-card").hidden = false;
    $("count").textContent = `${fmt(r.count)} admissions`;
    $("count-sub").textContent =
      `${(100 * r.count / r.total).toFixed(2)}% of ${fmt(r.total)} · query ${r.ms} ms`;
    $("edited").hidden = !out.edited;
    bars($("ages"), r.age_bins.map((b) => ({ label: b.from >= 90 ? "90+" : `${b.from}-${b.from + 9}`, n: b.n })), r.count);
    bars($("sex"), Object.entries(r.sex).map(([k, n]) => ({ label: k, n })), r.count);
    bars($("conditions"), r.top_conditions.map((x) => ({ label: condName[x.key] || x.key, n: x.n })), r.count);
    bars($("regions"), r.top_regions.map((x) => ({ label: regName[x.key] || x.key, n: x.n })), r.count);
    const cols = ["id", "age", "sex", "region", "admission_date", "length_of_stay", "triage", "conditions"];
    const head = ["ID", "Age", "Sex", "Region", "Admitted", "Stay (d)", "Triage", "Conditions"];
    $("sample").innerHTML = `<thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>` +
      r.sample.map((row) => `<tr>${cols.map((k) => k === "conditions"
        ? `<td class="conds"><div>${esc(row[k].map((x) => condName[x] || x).join(", "))}</div></td>`
        : `<td>${esc(k === "region" ? regName[row[k]] || row[k] : row[k])}</td>`).join("")}</tr>`).join("") +
      "</tbody>";
    refreshStats();
  } catch (e) {
    const issues = e.data?.detail?.issues;
    $("run-hint").textContent = issues ? "Blocked: fix the issues marked in red." : "The query failed.";
  } finally {
    $("run").disabled = !(state.report && state.report.runnable);
  }
}

async function refreshStats() {
  try {
    const s = await api("/api/stats");
    if (!s.drafts && !s.runs) return;
    $("stats").textContent = `Log: ${s.drafts} drafts, ${s.drafts_flagged || 0} with notes, ` +
      `${s.runs} runs, ${s.runs_edited || 0} edited before running.`;
  } catch (e) { /* stats are optional */ }
}

async function loadMeta() {
  const meta = await api("/api/meta");
  state.meta = meta;
  const status = $("status");
  status.classList.add(meta.reachable ? "ok" : "down");
  status.lastElementChild.textContent = meta.reachable
    ? [meta.model, meta.hardware].filter(Boolean).join(" · ")
    : "model offline";
  if (state.report) showReport(state.report);
}

async function init() {
  state.catalog = await api("/api/catalog");
  fillDatalists();
  loadMeta();
  $("examples").innerHTML = EXAMPLES.map((x) => `<button class="chip">${esc(x)}</button>`).join("");
  $("examples").addEventListener("click", (e) => {
    if (e.target.classList.contains("chip")) {
      $("request").value = e.target.textContent;
      draft();
    }
  });
  $("draft").addEventListener("click", draft);
  $("empty").addEventListener("click", startEmpty);
  $("run").addEventListener("click", run);
  $("add").addEventListener("click", () => {
    state.filter.push({ attr: "condition", op: "has", value: "" });
    renderClauses();
    scheduleReview();
  });
  $("request").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) draft();
  });
  $("request").addEventListener("input", () => { if (!$("filter-card").hidden) scheduleReview(); });
  $("clauses").addEventListener("change", onClauseEvent);
  $("clauses").addEventListener("click", (e) => { if (e.target.dataset.f === "remove") onClauseEvent(e); });
  refreshStats();
}

init();
