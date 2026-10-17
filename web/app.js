const EXAMPLES = {
  en: [
    "Patients aged 40 to 60 with diabetes",
    "Patients with diabetes and hypertension living in the North-West",
    "Very sick elderly patients",
    "Patients admitted during the 2023 summer heatwave",
    "Red-code patients with a fever above 39 degrees",
    "Asthma patients within 30 km of Milan",
    "Patients with long COVID",
    "Patients over 70 with a cardiovascular disease",
  ],
  it: [
    "Pazienti tra 40 e 60 anni con diabete",
    "Pazienti con diabete e ipertensione residenti nel Nord-Ovest",
    "Pazienti anziani molto gravi",
    "Pazienti ricoverati durante l'ondata di caldo dell'estate 2023",
    "Pazienti in codice rosso con febbre sopra i 39 gradi",
    "Pazienti asmatici entro 30 km da Milano",
    "Pazienti con long COVID",
    "Pazienti con più di 70 anni con una malattia cardiovascolare",
  ],
  fr: [
    "Patients de 40 à 60 ans atteints de diabète",
    "Patients diabétiques et hypertendus résidant dans le Nord-Ouest",
    "Patients âgés très malades",
    "Patients hospitalisés pendant la canicule de l'été 2023",
    "Patients en code rouge avec une fièvre supérieure à 39 degrés",
    "Patients asthmatiques à moins de 30 km de Milan",
    "Patients atteints de COVID long",
    "Patients de plus de 70 ans avec une maladie cardiovasculaire",
  ],
};
const FLAGS = {
  en: ["English", '<svg viewBox="0 0 60 30"><clipPath id="uk"><path d="M30 15h30v15zv15H0zH0V0zV0h30z"/></clipPath>' +
    '<path d="M0 0v30h60V0z" fill="#012169"/><path d="M0 0l60 30m0-30L0 30" stroke="#fff" stroke-width="6"/>' +
    '<path d="M0 0l60 30m0-30L0 30" clip-path="url(#uk)" stroke="#C8102E" stroke-width="4"/>' +
    '<path d="M30 0v30M0 15h60" stroke="#fff" stroke-width="10"/><path d="M30 0v30M0 15h60" stroke="#C8102E" stroke-width="6"/></svg>'],
  it: ["Italiano", '<svg viewBox="0 0 3 2"><path fill="#009246" d="M0 0h1v2H0z"/><path fill="#fff" d="M1 0h1v2H1z"/>' +
    '<path fill="#CE2B37" d="M2 0h1v2H2z"/></svg>'],
  fr: ["Français", '<svg viewBox="0 0 3 2"><path fill="#0055A4" d="M0 0h1v2H0z"/><path fill="#fff" d="M1 0h1v2H1z"/>' +
    '<path fill="#EF4135" d="M2 0h1v2H2z"/></svg>'],
};
const CHECKS = {
  validate: ["invalid", "error", "A value, operator or range that does not exist in the catalog."],
  unresolved: ["unresolved", "error",
    "A period or a distance nothing in the data can define: a named event, a radius around a city."],
  refusal: ["empty", "error", "No criterion at all: running it would select every patient."],
  contradiction: ["impossible", "error", "Criteria no patient can meet together."],
  coverage: ["coverage", "warning",
    "A part of the request with no criterion, or a criterion the request never asked for."],
  near_set: ["near-set", "warning",
    "A list that is almost a whole group (6 of 7 circulatory conditions), or one member when the request names the group."],
  conjunction: ["and / or", "warning",
    "\"and\" answered with \"any of\", or \"or\" split into criteria that must all hold."],
  value: ["value", "warning", "A sex or smoking status other than the one the request names."],
  provenance: ["source", "assumption",
    "A number, date or place nobody wrote: a threshold for \"elderly\", 1 January for \"in 2024\", a whole region for a city."],
};
// README, 13 October 2026: exact drafts out of 46 per model; every wrong draft carried a mark.
const RESIDUAL = [
  ["Qwen3.8-27B", 45], ["DeepSeek-V4-Flash", 44], ["MiMo-V2.6-Flash", 43],
  ["MiniCPM-V-4.7-35B-A3B", 41], ["Qwen3.8-Flash-Next", 40], ["MiniCPM5-2B", 25],
];
const REQUEST_CHECKS = new Set(["coverage", "near_set", "conjunction", "value", "provenance"]);
const LIST_OPS = new Set(["between", "in", "not_in", "has_any", "has_all", "has_none"]);
const PANEL = [
  ["Patient", ["age", "sex", "smoking", "bmi"]],
  ["Conditions", ["condition"]],
  ["Residence", ["region"]],
  ["Admission", ["admission_date", "length_of_stay", "triage", "systolic_bp", "temperature"]],
];
const FORM = PANEL.flatMap(([, keys]) => keys);
const NAMES = { region: "region of residence", condition: "conditions", triage: "triage code" };
const TRIAGE = { 1: "red", 2: "orange", 3: "light blue", 4: "green", 5: "white" };
const AREAS = ["nord_ovest", "nord_est", "centro", "sud", "isole"];
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
  ok: "From the request", hand: "Set by hand", any: "Any",
};

const $ = (id) => document.getElementById(id);
const state = {
  catalog: null, meta: null, filter: [], request: "", drafted: null, draftId: null, report: null,
  hand: new Set(), moved: new Set(), closed: new Set(),
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
const clone = (x) => JSON.parse(JSON.stringify(x));
const slug = (s) => String(s).normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
  .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const isMacro = (v) => typeof v === "string" && (/^(chapter|area|event|category)\s*:/i.test(v) || /^near\s*\(/i.test(v));
const isClause = (cl) => cl !== null && typeof cl === "object" && !Array.isArray(cl);
const inPanel = (cl) => isClause(cl) && FORM.includes(cl.attr);
const keyOf = (cl) => (inPanel(cl) ? cl.attr : "");
const idxsOf = (key, filt = state.filter) => filt.flatMap((cl, i) => (keyOf(cl) === key ? [i] : []));
const attrAt = (i) => keyOf(state.filter[i]);

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
  if (isMacro(t)) return t;
  if (LIST_OPS.has(op)) return t === "" ? [] : t.split(/\s*[,;]\s*/).map(parse);
  return parse(t);
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

function datalistFor(a) {
  return a && ["condition", "region", "sex", "smoking"].includes(a.key) ? `dl-${a.key}` : "";
}

function issueHtml(i) {
  const [tag, , help] = CHECKS[i.check] || [i.check, "", ""];
  return `<div class="issue ${i.level}"><span class="tag" tabindex="0" data-help="${esc(help)}">` +
    `${esc(tag)}</span><span class="msg">${esc(i.message)}</span></div>`;
}

// A reader returns null when the clauses do not fit its widget: the attribute then shows clause rows.

function members(key, v) {
  const m = typeof v === "string" && v.match(/^\s*(area|chapter|category)\s*:\s*(.+?)\s*$/i);
  if (!m) return Array.isArray(v) ? v : [v];
  const groups = key === "region" ? state.catalog.areas : state.catalog.chapters;
  const kind = m[1].toLowerCase() === "area" ? "region" : "condition";
  const g = kind === key && groups.find((x) => x.key === slug(m[2]));
  return g ? g.members : null;
}

function widgetKind(a) {
  if (["condition", "region", "triage"].includes(a.key)) return a.key;
  return a.kind === "enum" ? "enum" : "range";
}

function readRange(a, cls) {
  const ok = (v) => (a.kind === "date" ? typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)
    : typeof v === "number");
  const w = { lo: ["ge", ""], hi: ["le", ""] };
  for (const { op, value } of cls) {
    if (cls.length === 1 && op === "between" && Array.isArray(value) && value.length === 2 && value.every(ok)) {
      w.lo = ["ge", value[0]];
      w.hi = ["le", value[1]];
    } else if (cls.length === 1 && op === "eq" && ok(value)) {
      w.lo = ["ge", value];
      w.hi = ["le", value];
    } else if (["ge", "gt"].includes(op) && ok(value) && w.lo[1] === "") w.lo = [op, value];
    else if (["le", "lt"].includes(op) && ok(value) && w.hi[1] === "") w.hi = [op, value];
    else return null;
  }
  return w;
}

function writeRange(w) {
  const set = ([, v]) => v !== "";
  if (set(w.lo) && set(w.hi) && w.lo[0] === "ge" && w.hi[0] === "le") {
    return [{ op: "between", value: [w.lo[1], w.hi[1]] }];
  }
  return [w.lo, w.hi].filter(set).map(([op, value]) => ({ op, value }));
}

function readChoice(a, cls) {
  if (!cls.length) return { neg: false, vals: [] };
  const { op, value } = cls[0];
  const vals = members(a.key, value);
  if (cls.length > 1 || !["eq", "ne", "in", "not_in"].includes(op) || !vals
      || !vals.every((v) => a.values.includes(v))) return null;
  return { neg: op === "ne" || op === "not_in", vals: [...new Set(vals)] };
}

function writeChoice(a, w) {
  const { neg, vals } = w;
  if (!vals.length) return [];
  if (a.key === "region" && vals.length > 1) {
    const same = (g) => g.length === vals.length && g.every((x) => vals.includes(x));
    const area = state.catalog.areas.find((x) => same(x.members));
    if (area) return [{ op: neg ? "not_in" : "in", value: `area:${area.key}` }];
  }
  if (vals.length === 1) return [{ op: neg ? "ne" : "eq", value: vals[0] }];
  return [{ op: neg ? "not_in" : "in", value: vals }];
}

function readTriage(a, cls) {
  if (!cls.length) return { vals: [] };
  const { op, value } = cls[0];
  const xs = Array.isArray(value) ? value : [value];
  if (cls.length > 1 || !xs.every((x) => Number.isInteger(x) && x >= a.lo && x <= a.hi)) return null;
  const test = {
    eq: (x) => x === value, in: (x) => xs.includes(x), ge: (x) => x >= value, gt: (x) => x > value,
    le: (x) => x <= value, lt: (x) => x < value,
    between: (x) => xs.length === 2 && xs[0] <= xs[1] && xs[0] <= x && x <= xs[1],
  }[op];
  if (!test || (op === "between" && !(xs.length === 2 && xs[0] <= xs[1]))) return null;
  const dom = Array.from({ length: a.hi - a.lo + 1 }, (_, k) => a.lo + k);
  return { vals: dom.filter(test) };
}

function writeTriage(a, w) {
  const v = [...w.vals].sort((x, y) => x - y);
  if (!v.length) return [];
  if (v.length === 1) return [{ op: "eq", value: v[0] }];
  const [first, last] = [v[0], v[v.length - 1]];
  if (last - first !== v.length - 1) return [{ op: "in", value: v }];
  if (first === a.lo) return [{ op: "le", value: last }];
  if (last === a.hi) return [{ op: "ge", value: first }];
  return [{ op: "between", value: [first, last] }];
}

function readConditions(cls) {
  const w = { has: [], not: [], mode: "all" };
  let pos = 0;
  let neg = 0;
  for (const { op, value } of cls) {
    const vals = members("condition", value);
    if (!vals || !vals.every((v) => state.condName[v])) return null;
    if (op === "has" && !Array.isArray(value) && !isMacro(value)) w.has.push(value);
    else if ((op === "has_all" || op === "has_any") && !pos++) {
      w.has.push(...vals);
      if (op === "has_any") w.mode = "any";
    } else if (op === "has_none" && !neg++) w.not.push(...vals);
    else return null;
  }
  if (w.mode === "any" && cls.some((c) => c.op === "has")) return null;
  w.has = [...new Set(w.has)];
  w.not = [...new Set(w.not)];
  if (w.has.some((v) => w.not.includes(v))) return null;
  return w;
}

function writeConditions(w) {
  const out = [];
  const chapter = (vals) => state.catalog.chapters.find((c) =>
    vals.length > 1 && c.members.length === vals.length && c.members.every((x) => vals.includes(x)));
  if (w.has.length === 1) out.push({ op: "has", value: w.has[0] });
  else if (w.has.length) {
    const ch = w.mode === "any" && chapter(w.has);
    out.push({ op: w.mode === "any" ? "has_any" : "has_all", value: ch ? `chapter:${ch.key}` : w.has });
  }
  if (w.not.length) {
    const ch = chapter(w.not);
    out.push({ op: "has_none", value: ch ? `chapter:${ch.key}` : w.not });
  }
  return out;
}

const READ = { range: readRange, enum: readChoice, region: readChoice, triage: readTriage,
  condition: (a, cls) => readConditions(cls) };
const WRITE = { range: (a, w) => writeRange(w), enum: writeChoice, region: writeChoice,
  triage: writeTriage, condition: (a, w) => writeConditions(w) };

function readWidget(a) {
  return READ[widgetKind(a)](a, idxsOf(a.key).map((i) => state.filter[i]));
}

function setAttr(key, clauses, rerender = true) {
  const first = state.filter.findIndex((cl) => isClause(cl) && cl.attr === key);
  const rest = state.filter.filter((cl) => !(isClause(cl) && cl.attr === key));
  rest.splice(first < 0 ? rest.length : first, 0, ...clauses.map((cl) => ({ attr: key, ...cl })));
  state.filter = rest;
  touched(key);
  if (rerender) renderPanel();
  scheduleReview();
}

function touched(key) {
  state.hand.add(key);
  state.moved.delete(key);
}

function rangeHtml(a, w) {
  const type = a.kind === "date" ? "date" : "number";
  const step = a.kind === "float" ? "0.1" : "1";
  const limits = `min="${esc(a.lo)}" max="${esc(a.hi)}"` + (type === "number" ? ` step="${step}"` : "");
  const side = (s, ops, word) => `<select class="mini" data-act="${s}-op" aria-label="${esc(a.label)} ${word} operator">` +
    ops.map(([o, l]) => `<option value="${o}"${w[s][0] === o ? " selected" : ""}>${l}</option>`).join("") +
    `</select><input data-act="${s}" type="${type}" ${limits} value="${esc(w[s][1])}" ` +
    `placeholder="${s === "lo" ? "min" : "max"}" title="${esc(a.lo)} to ${esc(a.hi)}" ` +
    `aria-label="${esc(a.label)} ${word}">`;
  return `<div class="range-w">${side("lo", [["ge", "≥"], ["gt", "&gt;"]], "from")}` +
    `<span class="to">and</span>${side("hi", [["le", "≤"], ["lt", "&lt;"]], "to")}` +
    `<span class="unit">${esc(a.unit)}</span></div>`;
}

function pickHtml(v, label, on, extra = "") {
  return `<button type="button" class="pick${extra}" data-act="pick" data-v="${esc(v)}" ` +
    `aria-pressed="${on}">${esc(label)}</button>`;
}

function groupHtml(key, head, count, chips, act) {
  const open = state.closed.has(key) ? "" : " open";
  return `<details class="group" data-group="${esc(key)}"${open}><summary>` +
    `<span class="group-name">${head}</span><span class="count">${esc(count)}</span>` +
    `<button type="button" class="link" data-act="${act}" data-g="${esc(key)}">all</button>` +
    `</summary><div class="picks">${chips}</div></details>`;
}

function widgetHtml(a, w) {
  const kind = widgetKind(a);
  if (kind === "range") return rangeHtml(a, w);
  if (kind === "enum") {
    return `<div class="picks">${a.values.map((v) => pickHtml(v, v, w.vals.includes(v))).join("")}</div>`;
  }
  if (kind === "triage") {
    return `<div class="picks">${Object.entries(TRIAGE).map(([n, c]) =>
      pickHtml(n, `${n} ${c}`, w.vals.includes(Number(n)), ` tri tri-${n}`)).join("")}</div>`;
  }
  if (kind === "region") {
    return AREAS.map((k) => {
      const area = state.catalog.areas.find((x) => x.key === k);
      const on = area.members.filter((r) => w.vals.includes(r)).length;
      const chips = area.members.map((r) => pickHtml(r, state.regionName[r], w.vals.includes(r))).join("");
      return groupHtml(`area:${k}`, esc(area.name), on ? `${on} of ${area.members.length}` : "", chips, "area");
    }).join("");
  }
  return state.catalog.chapters.map((ch) => {
    const has = ch.members.filter((c) => w.has.includes(c)).length;
    const not = ch.members.filter((c) => w.not.includes(c)).length;
    const count = [has && `${has} of ${ch.members.length}`, not && `${not} excluded`].filter(Boolean).join(", ");
    const chips = ch.members.map((c) => {
      const s = w.has.includes(c) ? "has" : w.not.includes(c) ? "not" : "";
      const cond = state.catalog.conditions.find((x) => x.key === c);
      return `<button type="button" class="pick cond" data-act="cond" data-v="${c}" data-s="${s}" ` +
        `title="${esc(`${cond.name} (${cond.icd10})`)}">${esc(cond.name)}</button>`;
    }).join("");
    return groupHtml(`chapter:${ch.key}`, `${esc(ch.name)} <span class="icd">${esc(ch.icd10)}</span>`,
      count, chips, "chapter");
  }).join("");
}

function headControls(a, w) {
  if (!w) return "";
  const kind = widgetKind(a);
  if (kind === "enum" || kind === "region") {
    return `<select class="mini" data-act="neg" aria-label="${esc(a.label)}: is or is not">` +
      `<option value=""${w.neg ? "" : " selected"}>is</option>` +
      `<option value="1"${w.neg ? " selected" : ""}>is not</option></select>`;
  }
  if (kind === "condition" && w.has.length > 1) {
    return `<span class="seg" role="group" aria-label="Combine the ticked conditions">` +
      ["all", "any"].map((m) => `<button type="button" data-act="mode" data-mode="${m}" ` +
        `aria-pressed="${w.mode === m}">${m} of</button>`).join("") + "</span>";
  }
  return "";
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
  return input("value", valueToText(v), LIST_OPS.has(cl.op) ? "values, separated by commas" : datePh || "value");
}

function clauseHtml(i, a) {
  const cl = state.filter[i];
  const remove = `<button type="button" class="icon" data-f="remove" title="Remove" aria-label="Remove">✕</button>`;
  if (!isClause(cl)) {
    return `<div class="clause" data-idx="${i}"><div class="clause-fields wide">` +
      `<code>${esc(JSON.stringify(cl))}</code>${remove}</div></div>`;
  }
  const labels = a ? OP_LABEL[a.kind] : {};
  const ops = a && a.ops.includes(cl.op) ? a.ops : [cl.op, ...(a ? a.ops : [])];
  const opOpts = ops.map((o) =>
    `<option value="${esc(o)}" ${o === cl.op ? "selected" : ""}>${esc(labels[o] || o)}</option>`).join("");
  const attrSel = a ? "" : `<select data-f="attr" aria-label="Attribute"><option selected>${esc(cl.attr)}</option>` +
    state.catalog.attrs.map((x) => `<option value="${x.key}">${esc(x.label)}</option>`).join("") + "</select>";
  return `<div class="clause" data-idx="${i}"><div class="clause-fields${a ? "" : " wide"}">${attrSel}` +
    `<select data-f="op" aria-label="Operator">${opOpts}</select>${valueHtml(cl, a)}${remove}</div></div>`;
}

function facetHtml(a) {
  const key = a ? a.key : "";
  const idxs = idxsOf(key);
  if (!a && !idxs.length) return "";
  const w = a ? readWidget(a) : null;
  const body = w ? widgetHtml(a, w)
    : `<p class="hint">${a ? "This combination does not fit the panel. Edit it here, or reset it." : ""}</p>` +
      idxs.map((i) => clauseHtml(i, a)).join("");
  return `<div class="facet${w ? "" : " rows"}${w?.neg ? " neg" : ""}" data-attr="${key}">` +
    `<div class="facet-head"><span class="facet-name">${esc(a ? NAMES[key] || a.label : "Other criteria")}</span>` +
    `${headControls(a, w)}<span class="fstate any">${STATE.any}</span>` +
    `<button type="button" class="icon clear" data-act="clear" title="Reset to Any" aria-label="Reset to Any">✕</button>` +
    `</div><div class="facet-body">${body}</div><div class="from"></div></div>`;
}

function renderPanel() {
  const el = document.activeElement;
  const focus = el?.closest?.("#panel .facet") && el.dataset.act
    ? `.facet[data-attr="${el.closest(".facet").dataset.attr}"] ` + ["act", "v", "g", "mode"]
      .filter((k) => k in el.dataset).map((k) => `[data-${k}="${CSS.escape(el.dataset[k])}"]`).join("")
    : null;
  $("panel").innerHTML = PANEL.map(([title, keys]) =>
    `<section class="psec"><h3>${esc(title)}</h3>${keys.map((k) => facetHtml(attr(k))).join("")}</section>`).join("") +
    facetHtml(null);
  $("panel").classList.toggle("empty", !state.filter.length);
  if (focus) $("panel").querySelector(focus)?.focus();
  decorate();
}

// Issues and evidence are indexed on the filter the report was made for, which may be one edit behind.
const issueKey = (r, x) => (x.clause !== null ? keyOf(r.filter[x.clause]) : x.attr || null);
const visible = (r, x) => !(state.hand.has(issueKey(r, x)) && REQUEST_CHECKS.has(x.check));

function decorate() {
  const r = state.report;
  document.querySelectorAll("#panel .facet").forEach((facet) => {
    const key = facet.dataset.attr;
    const idxs = idxsOf(key);
    const hand = state.hand.has(key);
    const mine = r ? r.issues.filter((x) => issueKey(r, x) === key && visible(r, x)) : [];
    const levels = new Set(mine.map((i) => i.level));
    const ev = r ? idxsOf(key, r.filter).flatMap((i) => r.evidence?.[i] || []) : [];
    const s = levels.has("error") ? "fix"
      : mine.length && !idxs.length ? "missing"
      : levels.has("warning") ? "check"
      : !idxs.length ? "any"
      : hand ? "hand"
      : levels.has("assumption") || !ev.length ? "assumed" : "ok";
    const badge = facet.querySelector(".fstate");
    badge.className = `fstate ${s}`;
    badge.textContent = STATE[s];
    const from = facet.querySelector(".from");
    from.innerHTML = !idxs.length || !r || hand ? ""
      : ev.length ? "from " + ev.map((x) => `<q>${esc(x.text)}</q>`).join(" ") : "not in the request";
    from.classList.toggle("none", !!idxs.length && !ev.length);
    badge.title = mine.map((x) => x.message).join("\n");
    facet.classList.toggle("set", idxs.length > 0);
    facet.classList.toggle("has-error", levels.has("error"));
    facet.classList.toggle("moved", state.moved.has(key));
  });
}

function onPanelClick(e) {
  const t = e.target.closest("[data-act], [data-f]");
  if (!t || t.tagName === "SELECT" || t.tagName === "INPUT") return;
  if (t.closest("summary")) e.preventDefault();
  if (t.dataset.f) return onClauseEvent(e);
  const key = t.closest(".facet")?.dataset.attr;
  const a = key && attr(key);
  const act = t.dataset.act;
  if (act === "clear" && !key) {
    state.filter = state.filter.filter(inPanel);
    renderPanel();
    return scheduleReview();
  }
  if (act === "clear") return setAttr(key, []);
  if (!a) return;
  const w = readWidget(a);
  if (!w) return;
  const v = widgetKind(a) === "triage" ? Number(t.dataset.v) : t.dataset.v;
  const toggle = (list, x) => (list.includes(x) ? list.filter((y) => y !== x) : [...list, x]);
  if (act === "pick") w.vals = toggle(w.vals, v);
  else if (act === "area") {
    const group = members("region", t.dataset.g);
    const all = group.every((r) => w.vals.includes(r));
    w.vals = all ? w.vals.filter((r) => !group.includes(r)) : [...new Set([...w.vals, ...group])];
  } else if (act === "cond") {
    if (w.has.includes(v)) {
      w.has = w.has.filter((x) => x !== v);
      w.not.push(v);
    } else if (w.not.includes(v)) w.not = w.not.filter((x) => x !== v);
    else w.has.push(v);
  } else if (act === "chapter") {
    const group = members("condition", t.dataset.g);
    const all = group.every((c) => w.has.includes(c));
    if (!all && !w.has.length) w.mode = "any";
    w.has = all ? w.has.filter((c) => !group.includes(c)) : [...new Set([...w.has, ...group])];
    w.not = w.not.filter((c) => !group.includes(c));
  } else if (act === "mode") w.mode = t.dataset.mode;
  else return;
  setAttr(key, WRITE[widgetKind(a)](a, w));
}

function onPanelChange(e) {
  const t = e.target;
  if (t.dataset.f) return onClauseEvent(e);
  const key = t.closest(".facet")?.dataset.attr;
  const a = key && attr(key);
  const w = a && readWidget(a);
  if (!w) return;
  const act = t.dataset.act;
  if (act === "neg") {
    w.neg = !!t.value;
    return setAttr(key, WRITE[widgetKind(a)](a, w));
  }
  const side = act.slice(0, 2);
  if (act.endsWith("-op")) w[side][0] = t.value;
  else if (t.value === "" || a.kind === "date") w[side][1] = t.value;
  else w[side][1] = Number.isNaN(Number(t.value)) ? "" : Number(t.value);
  setAttr(key, writeRange(w), false);
}

function onClauseEvent(e) {
  const f = e.target.dataset.f;
  const row = e.target.closest(".clause");
  if (!row) return;
  const idx = Number(row.dataset.idx);
  const cl = state.filter[idx];
  const a = isClause(cl) ? attr(cl.attr) : null;
  touched(attrAt(idx));
  if (f === "remove") {
    state.filter.splice(idx, 1);
    renderPanel();
  } else if (f === "attr") {
    const b = attr(e.target.value);
    const [op, value] = b.key === "region" ? ["in", []] : DEFAULT[b.kind];
    state.filter[idx] = { attr: b.key, op, value: clone(value) };
    renderPanel();
  } else if (f === "op") {
    cl.op = e.target.value;
    if (!isMacro(cl.value)) {
      const v = cl.value;
      if (cl.op === "between") cl.value = Array.isArray(v) ? [v[0] ?? "", v[1] ?? ""] : [v ?? "", ""];
      else if (LIST_OPS.has(cl.op)) cl.value = Array.isArray(v) ? v.filter((x) => x !== "") : v === "" || v == null ? [] : [v];
      else if (Array.isArray(v)) cl.value = v[0] ?? "";
    }
    renderPanel();
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
    if (!state.filter.length && !state.request) return showReport(null);
    const sent = JSON.stringify(state.filter);
    try {
      const r = await api("/api/review", { request: state.request, filter: state.filter });
      if (sent === JSON.stringify(state.filter)) showReport(r);
    } catch (e) {
      $("run-hint").textContent = "The server did not answer.";
    }
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

function showReading(r) {
  const evidence = r.evidence || [];
  $("echo").innerHTML = echoHtml(state.request, evidence);
  $("echo").hidden = !state.request;
  $("reading").innerHTML = r.readable.map((txt, i) => {
    const ev = evidence[i] || [];
    const hand = state.hand.has(keyOf(r.filter[i]));
    const from = hand ? "set by hand" : ev.length ? ev.map((e) => `<q>${esc(e.text)}</q>`).join(" ") : "not in the request";
    const own = r.issues.filter((x) => x.clause === i && visible(r, x));
    return `<li data-c="${i}" class="${hand ? "byhand" : ev.length ? "" : "unsourced"}">` +
      `<span class="from">${from}</span><span class="to">${esc(txt)}</span>` +
      (own.length ? `<div class="li-issues">${own.map(issueHtml).join("")}</div>` : "") + "</li>";
  }).join("");
  $("explain").innerHTML = r.explanation.map((x) => `<li>${esc(x)}</li>`).join("");
}

function highlight(idxs) {
  const on = (el) => el.dataset.c.split(" ").some((c) => idxs.includes(Number(c)));
  document.querySelectorAll("#echo mark, #reading li").forEach((el) => el.classList.toggle("hot", on(el)));
  const keys = new Set(idxs.map((i) => keyOf(state.report?.filter[i])));
  document.querySelectorAll("#panel .facet").forEach((el) =>
    el.classList.toggle("hot", idxs.length > 0 && keys.has(el.dataset.attr)));
}

function onHover(e) {
  const el = e.target.closest("[data-c], .facet");
  if (!el) return highlight([]);
  highlight(el.classList.contains("facet") ? idxsOf(el.dataset.attr, state.report?.filter || [])
    : el.dataset.c.split(" ").map(Number));
}

function showReport(r) {
  state.report = r;
  decorate();
  $("read-card").hidden = !r;
  $("placeholder").hidden = !!r || !$("result-card").hidden;
  if (!r) {
    $("run").disabled = true;
    $("run-hint").textContent = "";
    return;
  }
  $("general-issues").innerHTML = r.issues.filter((x) => x.clause === null && visible(r, x))
    .map(issueHtml).join("");
  showReading(r);
  $("sql").textContent = r.sql || "No SQL until the blocking issues are fixed.";
  $("sql").classList.toggle("blocked", !r.sql);
  const errors = r.issues.filter((i) => i.level === "error").length;
  const shown = r.issues.filter((x) => x.level !== "error" && visible(r, x)).length;
  $("run").disabled = !r.runnable;
  $("run").textContent = `Run on ${fmt(state.meta?.patients || 0)} admissions`;
  $("run-hint").textContent = errors
    ? `${errors} blocking issue${errors > 1 ? "s" : ""} to fix first`
    : shown ? `${shown} note${shown > 1 ? "s" : ""} to read before running` : "No issues found";
}

// The endpoint gives no progress, so the bar follows the usual latency and never claims to be done.
function startProgress() {
  const t0 = performance.now();
  const who = [state.meta?.model, state.meta?.hardware].filter(Boolean).join(" on ");
  const fill = $("progress").firstElementChild;
  const tick = () => {
    const s = (performance.now() - t0) / 1000;
    fill.style.width = `${(95 * (1 - Math.exp(-s / 8))).toFixed(1)}%`;
    const slow = s > 45 ? ", the first request stalled: trying a fresh one"
      : s > 15 ? ", the endpoint is shared and a queue can take a minute" : "";
    $("draft-info").textContent = `Reading the request${who ? ` with ${who}` : ""}: ${Math.floor(s)} s${slow}`;
  };
  $("progress").hidden = false;
  $("progress").classList.remove("done");
  $("panel-card").classList.add("busy");
  tick();
  const timer = setInterval(tick, 200);
  return () => {
    clearInterval(timer);
    fill.style.width = "100%";
    $("progress").classList.add("done");
    $("panel-card").classList.remove("busy");
    setTimeout(() => { $("progress").hidden = true; fill.style.width = "0"; }, 600);
  };
}

async function draft() {
  const request = $("request").value.trim();
  if (!request) return $("request").focus();
  $("draft").disabled = true;
  $("draft").textContent = "Setting the filters…";
  const stop = startProgress();
  try {
    const out = await api("/api/draft", { request });
    clearTimeout(reviewTimer);
    state.filter = out.filter;
    state.drafted = clone(out.filter);
    state.draftId = out.id;
    state.request = request;
    state.hand = new Set();
    state.moved = new Set(out.filter.filter(inPanel).map((cl) => cl.attr));
    state.closed = untouchedGroups();
    $("note").hidden = !out.note;
    $("note").textContent = out.note ? `Model note: ${out.note}` : "";
    $("draft-info").textContent = out.saved
      ? `No live draft right now (${out.saved.reason}). This is the draft ${out.saved.model} wrote for this example on ${out.saved.date}; the checks ran just now. Nothing runs until you press Run.`
      : out.llm.error
        ? `${out.llm.error}. You can still set the filters by hand.`
        : `Drafted by ${out.llm.model} in ${(out.llm.ms / 1000).toFixed(1)} s. Nothing runs until you press Run.`;
    renderPanel();
    showReport(out);
    const first = document.querySelector("#panel .facet.moved");
    if (first) document.querySelector(".panel-card").scrollTo({ top: first.offsetTop - 40, behavior: "smooth" });
    stop();
  } catch (e) {
    stop();
    $("draft-info").textContent = "The server did not answer.";
  } finally {
    $("draft").disabled = false;
    $("draft").textContent = "Set the filters";
  }
}

function showExamples(lang) {
  $("examples").innerHTML = EXAMPLES[lang].map((x) => `<button type="button" class="chip" lang="${lang}">${esc(x)}</button>`).join("");
  document.querySelectorAll("#langs .flag").forEach((b) => b.setAttribute("aria-pressed", b.dataset.lang === lang));
}

function residualChart() {
  const legend = `<div class="rlegend"><span><i class="exact"></i>exact</span>` +
    `<span><i class="marked"></i>wrong, marked on screen</span>` +
    `<span><i class="unmarked"></i>wrong, unmarked: none</span></div>`;
  $("residual-chart").innerHTML = legend + RESIDUAL.map(([model, exact]) => {
    const wrong = 46 - exact;
    return `<div class="rrow" title="${model}: ${exact} exact, ${wrong} wrong and marked, 0 wrong and unmarked">` +
      `<span class="rname">${model}</span><span class="rbar">` +
      `<span class="exact" style="width:${(100 * exact / 46).toFixed(2)}%"></span>` +
      `<span class="marked" style="width:${(100 * wrong / 46).toFixed(2)}%"></span></span>` +
      `<span class="rnum">${exact} / ${wrong} / <b>0</b></span></div>`;
  }).join("");
}

function untouchedGroups() {
  const closed = new Set();
  const cond = readWidget(attr("condition"));
  const region = readWidget(attr("region"));
  if (cond) {
    state.catalog.chapters.filter((ch) => !ch.members.some((c) => cond.has.includes(c) || cond.not.includes(c)))
      .forEach((ch) => closed.add(`chapter:${ch.key}`));
  }
  if (region) {
    state.catalog.areas.filter((x) => AREAS.includes(x.key) && !x.members.some((r) => region.vals.includes(r)))
      .forEach((x) => closed.add(`area:${x.key}`));
  }
  return closed;
}

function clearAll() {
  clearTimeout(reviewTimer);
  state.closed = new Set();
  Object.assign(state, { filter: [], request: "", drafted: null, draftId: null });
  state.hand = new Set();
  state.moved = new Set();
  $("note").hidden = true;
  $("draft-info").textContent = "";
  renderPanel();
  showReport(null);
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
      request: state.request, filter: state.filter, drafted: state.drafted, draft_id: state.draftId,
    });
    const r = out.result;
    $("placeholder").hidden = true;
    $("result-card").hidden = false;
    $("count").textContent = `${fmt(r.count)} admissions`;
    $("count-sub").textContent =
      `${(100 * r.count / r.total).toFixed(2)}% of ${fmt(r.total)} · query ${r.ms} ms`;
    $("edited").hidden = !out.edited;
    funnel(r.steps || [], out.readable, r.total);
    bars($("ages"), r.age_bins.map((b) => ({ label: b.from >= 90 ? "90+" : `${b.from}-${b.from + 9}`, n: b.n })), r.count);
    bars($("sex"), Object.entries(r.sex).map(([k, n]) => ({ label: k, n })), r.count);
    bars($("conditions"), r.top_conditions.map((x) => ({ label: state.condName[x.key] || x.key, n: x.n })), r.count);
    bars($("regions"), r.top_regions.map((x) => ({ label: state.regionName[x.key] || x.key, n: x.n })), r.count);
    const cols = ["id", "age", "sex", "region", "admission_date", "length_of_stay", "triage", "conditions"];
    const head = ["ID", "Age", "Sex", "Region", "Admitted", "Stay (d)", "Triage", "Conditions"];
    const cname = (x) => state.condName[x] || x;
    $("sample").innerHTML = `<thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>` +
      r.sample.map((row) => `<tr>${cols.map((k) => k === "conditions"
        ? `<td class="conds" title="${esc(row[k].map(cname).join(", "))}"><div>` +
          `${esc(row[k].slice(0, 4).map(cname).join(", "))}` +
          `${row[k].length > 4 ? ` <span class="more">+${row[k].length - 4}</span>` : ""}</div></td>`
        : `<td>${esc(k === "region" ? state.regionName[row[k]] || row[k] : row[k])}</td>`).join("")}</tr>`).join("") +
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
  for (const ch of state.catalog.chapters) {
    ch.members = state.catalog.conditions.filter((c) => c.chapter === ch.key).map((c) => c.key);
  }
  state.condName = Object.fromEntries(state.catalog.conditions.map((x) => [x.key, x.name]));
  state.regionName = Object.fromEntries(state.catalog.regions.map((x) => [x.key, x.name]));
  fillDatalists();
  loadMeta();
  $("langs").innerHTML = Object.entries(FLAGS).map(([k, [name, svg]]) =>
    `<button type="button" class="flag" data-lang="${k}" title="Examples in ${name}" aria-label="Examples in ${name}" ` +
    `aria-pressed="${k === "en"}">${svg}</button>`).join("");
  showExamples("en");
  $("langs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-lang]");
    if (b) showExamples(b.dataset.lang);
  });
  $("examples").addEventListener("click", (e) => {
    if (e.target.classList.contains("chip")) {
      $("request").value = e.target.textContent;
      draft();
    }
  });
  $("checks-list").innerHTML = Object.values(CHECKS).map(([tag, level, help]) =>
    `<li><span class="pill ${level}">${esc(tag)}</span><span>${esc(help)}</span></li>`).join("");
  $("draft").addEventListener("click", draft);
  residualChart();
  $("about-open").addEventListener("click", () => $("about").showModal());
  $("about-close").addEventListener("click", () => $("about").close());
  $("about").addEventListener("click", (e) => { if (e.target === $("about")) $("about").close(); });
  $("clear").addEventListener("click", clearAll);
  $("run").addEventListener("click", run);
  $("request").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) draft();
  });
  $("panel").addEventListener("click", onPanelClick);
  $("panel").addEventListener("change", onPanelChange);
  $("panel").addEventListener("toggle", (e) => {
    const g = e.target.dataset?.group;
    if (g) e.target.open ? state.closed.delete(g) : state.closed.add(g);
  }, true);
  for (const id of ["panel", "echo", "reading"]) {
    $(id).addEventListener("mouseover", onHover);
    $(id).addEventListener("mouseleave", () => highlight([]));
  }
  renderPanel();
  refreshStats();
}

init();
