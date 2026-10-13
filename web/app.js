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
  near_set: "near-set", conjunction: "and / or", provenance: "source", contradiction: "impossible",
  value: "value",
};
const LIST_OPS = new Set(["between", "in", "not_in", "has_any", "has_all", "has_none"]);
const FORM = ["condition", "age", "sex", "region", "admission_date", "length_of_stay", "triage",
  "systolic_bp", "temperature", "bmi", "smoking"];
const OP_LABEL = {
  int: { between: "between", ge: "at least", gt: "more than", le: "at most", lt: "less than", eq: "exactly", in: "one of" },
  float: { between: "between", ge: "at least", gt: "more than", le: "at most", lt: "less than" },
  date: { between: "between", ge: "from", gt: "after", le: "until", lt: "before", eq: "on" },
  enum: { eq: "is", ne: "is not", in: "is one of", not_in: "is none of" },
  set: { has: "has", has_all: "has all of", has_any: "has any of", has_none: "has none of" },
};
const DEFAULT = { int: ["ge", ""], float: ["ge", ""], date: ["between", ["", ""]], enum: ["eq", ""], set: ["has", ""] };
const STATE = {
  fix: "Fix before Run", check: "Check", missing: "Mentioned, not filtered", assumed: "Assumed",
  ok: "From the request", any: "Any",
};

const $ = (id) => document.getElementById(id);
const state = {
  catalog: null, meta: null, filter: [], drafted: null, draftId: null, report: null, reportRequest: "",
};
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

const isMacro = (v) => typeof v === "string" && (/^(chapter|area|event|category)\s*:/i.test(v) || /^near\s*\(/i.test(v));
const isClause = (cl) => cl !== null && typeof cl === "object" && !Array.isArray(cl);

function blank(a) {
  const [op, value] = a.key === "region" ? ["in", []] : DEFAULT[a.kind];
  return { attr: a.key, op, value: JSON.parse(JSON.stringify(value)) };
}

function valueHtml(cl, a) {
  const v = cl.value;
  const input = (f, val, ph) =>
    `<input data-f="${f}" aria-label="${ph}" list="${datalistFor(a)}" value="${esc(val)}" placeholder="${ph}">`;
  if (!a || isMacro(v)) return input("value", valueToText(v), "value");
  const datePh = a.kind === "date" ? "YYYY-MM-DD" : "";
  if (cl.op === "between") {
    const [lo, hi] = Array.isArray(v) ? v : [v, ""];
    return `<span class="range">${input("lo", lo ?? "", datePh || "from")}<span>and</span>` +
      `${input("hi", hi ?? "", datePh || "to")}</span>`;
  }
  if (a.kind === "enum" && a.key !== "region" && !LIST_OPS.has(cl.op)) {
    const opts = ["", ...a.values].map((x) =>
      `<option value="${esc(x)}" ${x === v ? "selected" : ""}>${x ? esc(x) : "choose"}</option>`);
    if (v && !a.values.includes(v)) opts.push(`<option selected>${esc(v)}</option>`);
    return `<select data-f="value" aria-label="Value">${opts.join("")}</select>`;
  }
  return input("value", valueToText(v), LIST_OPS.has(cl.op) ? "values, separated by commas" : datePh || "value");
}

function clauseHtml(i, a) {
  const cl = state.filter[i];
  const tail = `<div class="readable"></div><div class="from"></div><div class="clause-issues"></div></div>`;
  const remove = `<button class="icon" data-f="remove" title="Remove" aria-label="Remove">✕</button>`;
  if (!isClause(cl)) {
    return `<div class="clause" data-idx="${i}"><div class="clause-fields wide">` +
      `<code>${esc(JSON.stringify(cl))}</code>${remove}</div>${tail}`;
  }
  const labels = a ? OP_LABEL[a.kind] : {};
  const ops = a && a.ops.includes(cl.op) ? a.ops : [cl.op, ...(a ? a.ops : [])];
  const opOpts = ops.map((o) =>
    `<option value="${esc(o)}" ${o === cl.op ? "selected" : ""}>${esc(labels[o] || o)}</option>`).join("");
  const attrSel = a ? "" : `<select data-f="attr" aria-label="Attribute"><option selected>${esc(cl.attr)}</option>` +
    state.catalog.attrs.map((x) => `<option value="${x.key}">${esc(x.label)}</option>`).join("") + "</select>";
  return `<div class="clause" data-idx="${i}"><div class="clause-fields${a ? "" : " wide"}">${attrSel}` +
    `<select data-f="op" aria-label="Operator">${opOpts}</select>${valueHtml(cl, a)}${remove}</div>${tail}`;
}

function facetHtml(a, idxs) {
  const name = a ? a.label : "other";
  const add = a ? `<button class="icon add" data-f="add" data-attr="${a.key}" title="Add a ${esc(name)} criterion" ` +
    `aria-label="Add a ${esc(name)} criterion">+</button>` : "";
  return `<div class="facet${idxs.length ? "" : " empty"}" data-attr="${a ? a.key : ""}">` +
    `<div class="facet-head"><span class="facet-name">${esc(name)}</span>` +
    `<span class="fstate any">${STATE.any}</span>${add}</div>` +
    `${idxs.map((i) => clauseHtml(i, a)).join("")}<div class="facet-issues"></div></div>`;
}

function renderForm() {
  const byAttr = {};
  const other = [];
  state.filter.forEach((cl, i) => {
    const key = isClause(cl) ? cl.attr : null;
    if (FORM.includes(key)) (byAttr[key] ||= []).push(i);
    else other.push(i);
  });
  $("clauses").innerHTML = FORM.map((k) => facetHtml(attr(k), byAttr[k] || [])).join("") +
    (other.length ? facetHtml(null, other) : "");
}

function onClauseEvent(e) {
  const f = e.target.dataset.f;
  if (f === "add") {
    state.filter.push(blank(attr(e.target.dataset.attr)));
    renderForm();
    const row = document.querySelector(`.clause[data-idx="${state.filter.length - 1}"]`);
    row?.querySelector('input, select[data-f="value"]')?.focus();
    return scheduleReview();
  }
  const row = e.target.closest(".clause");
  if (!row) return;
  const idx = Number(row.dataset.idx);
  const cl = state.filter[idx];
  const a = isClause(cl) ? attr(cl.attr) : null;
  if (f === "remove") {
    state.filter.splice(idx, 1);
    renderForm();
  } else if (f === "attr") {
    state.filter[idx] = blank(attr(e.target.value));
    renderForm();
  } else if (f === "op") {
    cl.op = e.target.value;
    if (!isMacro(cl.value)) {
      const v = cl.value;
      if (cl.op === "between") cl.value = Array.isArray(v) ? [v[0] ?? "", v[1] ?? ""] : [v ?? "", ""];
      else if (LIST_OPS.has(cl.op)) cl.value = Array.isArray(v) ? v.filter((x) => x !== "") : v === "" || v == null ? [] : [v];
      else if (Array.isArray(v)) cl.value = v[0] ?? "";
    }
    renderForm();
  } else if (f === "lo" || f === "hi") {
    const v = Array.isArray(cl.value) ? [...cl.value] : ["", ""];
    v[f === "lo" ? 0 : 1] = textToValue(e.target.value, a, "eq");
    cl.value = v;
  } else if (f === "value") {
    cl.value = textToValue(e.target.value, a, cl.op);
  } else {
    return;
  }
  scheduleReview();
}

function scheduleReview() {
  clearTimeout(reviewTimer);
  reviewTimer = setTimeout(async () => {
    const request = $("request").value;
    const report = await api("/api/review", { request, filter: state.filter });
    showReport(report, request);
  }, 250);
}

function echoHtml(request, evidence) {
  const cuts = new Set([0, request.length]);
  evidence.forEach((ev) => ev.forEach((e) => { cuts.add(e.start); cuts.add(e.end); }));
  const pts = [...cuts].sort((a, b) => a - b);
  let html = "";
  for (let k = 0; k < pts.length - 1; k++) {
    const [a, b] = [pts[k], pts[k + 1]];
    const owners = evidence.flatMap((ev, i) => (ev.some((e) => e.start <= a && b <= e.end) ? [i] : []));
    const text = esc(request.slice(a, b));
    html += owners.length ? `<mark data-c="${owners.join(" ")}">${text}</mark>` : text;
  }
  return html;
}

function showReading(r, request) {
  const evidence = r.evidence || [];
  $("echo").innerHTML = echoHtml(request, evidence);
  $("reading").innerHTML = r.readable.map((txt, i) => {
    const ev = evidence[i] || [];
    const from = ev.length ? ev.map((e) => `<q>${esc(e.text)}</q>`).join(" ") : "not in the request";
    return `<li data-c="${i}" class="${ev.length ? "" : "unsourced"}">` +
      `<span class="from">${from}</span><span class="to">${esc(txt)}</span></li>`;
  }).join("");
  $("explain").innerHTML = r.explanation.map((x) => `<li>${esc(x)}</li>`).join("");
  $("explain-box").hidden = r.readable.length === 0;
}

function highlight(idx) {
  const on = (el) => idx !== null && el.dataset.c.split(" ").includes(String(idx));
  document.querySelectorAll("#echo mark, #reading li").forEach((el) => el.classList.toggle("hot", on(el)));
  document.querySelectorAll(".clause").forEach((el) => el.classList.toggle("hot", el.dataset.idx === String(idx)));
}

function onHover(e) {
  const el = e.target.closest("[data-c], .clause");
  if (!el) return highlight(null);
  highlight(el.classList.contains("clause") ? Number(el.dataset.idx) : Number(el.dataset.c.split(" ")[0]));
}

function showReport(r, request) {
  state.report = r;
  state.reportRequest = request ?? state.reportRequest ?? "";
  const evidence = r.evidence || [];
  document.querySelectorAll(".clause").forEach((row) => {
    const idx = Number(row.dataset.idx);
    const own = r.issues.filter((i) => i.clause === idx);
    const ev = evidence[idx] || [];
    const from = row.querySelector(".from");
    row.querySelector(".readable").textContent = r.readable[idx] || "";
    from.innerHTML = ev.length ? "from " + ev.map((x) => `<q>${esc(x.text)}</q>`).join(" ") : "not in the request";
    from.classList.toggle("none", !ev.length);
    row.querySelector(".clause-issues").innerHTML = own.map(issueHtml).join("");
    row.classList.toggle("has-error", own.some((i) => i.level === "error"));
  });
  const facets = new Set();
  document.querySelectorAll(".facet").forEach((facet) => {
    const key = facet.dataset.attr;
    facets.add(key);
    const idxs = [...facet.querySelectorAll(".clause")].map((x) => Number(x.dataset.idx));
    const mine = r.issues.filter((i) => idxs.includes(i.clause));
    const loose = r.issues.filter((i) => i.clause === null && i.attr && i.attr === key);
    facet.querySelector(".facet-issues").innerHTML = loose.map(issueHtml).join("");
    const levels = new Set(mine.concat(loose).map((i) => i.level));
    const unsourced = idxs.some((i) => !(evidence[i] || []).length);
    const s = levels.has("error") ? "fix"
      : loose.length && !idxs.length ? "missing"
      : levels.has("warning") ? "check"
      : levels.has("assumption") || unsourced ? "assumed"
      : idxs.length ? "ok" : "any";
    const badge = facet.querySelector(".fstate");
    badge.className = `fstate ${s}`;
    badge.textContent = STATE[s];
  });
  $("general-issues").innerHTML = r.issues
    .filter((i) => i.clause === null && !(i.attr && facets.has(i.attr))).map(issueHtml).join("");
  showReading(r, state.reportRequest);
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
    renderForm();
    showReport(out, request);
  } catch (e) {
    $("draft-info").textContent = "The server did not answer.";
  } finally {
    $("draft").disabled = false;
  }
}

function startEmpty() {
  state.filter = [];
  state.drafted = null;
  state.draftId = null;
  $("filter-card").hidden = false;
  $("note").hidden = true;
  renderForm();
  scheduleReview();
}

function bars(el, items, total) {
  const max = Math.max(1, ...items.map((x) => x.n));
  el.innerHTML = items.map((x) => `
    <div class="bar"><span class="name" title="${esc(x.label)}">${esc(x.label)}</span>
      <span class="track"><span class="fill" style="width:${(100 * x.n / max).toFixed(1)}%"></span></span>
      <span class="n">${total ? (100 * x.n / total).toFixed(1) + "%" : fmt(x.n)}</span></div>`).join("");
}

function funnel(steps, readable, total) {
  const rows = [{ label: "All admissions", n: total, prev: null }]
    .concat(steps.map((n, i) => ({ label: readable[i], n, prev: i ? steps[i - 1] : total })));
  $("funnel").innerHTML = rows.map((x) => {
    const cut = x.prev ? 1 - x.n / x.prev : 0;
    let note = "";
    if (x.prev !== null && x.n === 0) note = `<span class="flag empty">no one left</span>`;
    else if (x.prev !== null && x.n === x.prev) note = `<span class="flag">removes no one</span>`;
    else if (x.prev !== null) note = `<span class="cut">-${(100 * cut).toFixed(cut < 0.01 ? 2 : 0)}%</span>`;
    const w = x.n ? Math.max(0.4, (100 * x.n) / total) : 0;
    return `<div class="step"><span class="name" title="${esc(x.label)}">${esc(x.label)}</span>` +
      `<span class="track"><span class="fill" style="width:${w.toFixed(2)}%"></span></span>` +
      `<span class="n">${fmt(x.n)}</span>${note || "<span></span>"}</div>`;
  }).join("");
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
    funnel(r.steps || [], out.readable, r.total);
    bars($("ages"), r.age_bins.map((b) => ({ label: b.from >= 90 ? "90+" : `${b.from}-${b.from + 9}`, n: b.n })), r.count);
    bars($("sex"), Object.entries(r.sex).map(([k, n]) => ({ label: k, n })), r.count);
    bars($("conditions"), r.top_conditions.map((x) => ({ label: condName[x.key] || x.key, n: x.n })), r.count);
    bars($("regions"), r.top_regions.map((x) => ({ label: regName[x.key] || x.key, n: x.n })), r.count);
    const cols = ["id", "age", "sex", "region", "admission_date", "length_of_stay", "triage", "conditions"];
    const head = ["ID", "Age", "Sex", "Region", "Admitted", "Stay (d)", "Triage", "Conditions"];
    $("sample").innerHTML = `<thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>` +
      r.sample.map((row) => `<tr>${cols.map((k) => k === "conditions"
        ? `<td class="conds" title="${esc(row[k].map((x) => condName[x] || x).join(", "))}"><div>` +
          `${esc(row[k].slice(0, 4).map((x) => condName[x] || x).join(", "))}` +
          `${row[k].length > 4 ? ` <span class="more">+${row[k].length - 4}</span>` : ""}</div></td>`
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
  $("request").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) draft();
  });
  $("request").addEventListener("input", () => { if (!$("filter-card").hidden) scheduleReview(); });
  $("clauses").addEventListener("change", onClauseEvent);
  for (const id of ["clauses", "echo", "reading"]) {
    $(id).addEventListener("mouseover", onHover);
    $(id).addEventListener("mouseleave", () => highlight(null));
  }
  $("clauses").addEventListener("click", (e) => {
    if (["remove", "add"].includes(e.target.dataset.f)) onClauseEvent(e);
  });
  refreshStats();
}

init();
