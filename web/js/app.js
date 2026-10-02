// India Drought & Groundwater Watch - front end (no build step; D3 v7 global).
// Data: web/data/*.json written by the pipeline. All UI strings: i18n/en.json.

const DATA = "data/";
const QUAD = { F: "fine", H: "hidden_drought", B: "buffered", D: "double_drought" };
const QUAD_VAR = {
  fine: "--q-fine", buffered: "--q-buffered", hidden_drought: "--q-hidden",
  double_drought: "--q-double",
};
const RAIN_VAR = {
  "Large Excess": "--wet-2", "Excess": "--wet-1", "Normal": "--neutral",
  "Deficient": "--sev-1", "Large Deficient": "--sev-3", "No Rain": "--sev-4",
};
const STRESS_VAR = {
  "Safe": "--neutral", "Semi-critical": "--sev-1", "Critical": "--sev-3",
  "Over-exploited": "--sev-4", "Saline": "--saline",
};
const IDM_VAR = { none: "--neutral", d0: "--sev-0", d1: "--sev-1", d2: "--sev-2", d3: "--sev-3", d4: "--sev-4" };
const LAYERS = ["quadrant", "rain", "gw", "stress", "idm"];
const CYCLE_MONTH = { "01": "Jan", "05": "May", "08": "Aug", "11": "Nov" };

let S = null;          // i18n strings
const st = { layer: "quadrant", snapshot: "now", selected: null, view: "map", filter: null, sort: ["category", 1] };
const cache = { snaps: {}, dist: {} };
let geo, status, histIndex, names = {}, paths, outlinePath;

// ---------------- helpers ----------------
const t = (k, vars = {}) => (S && S[k] !== undefined ? S[k] : k).replace(/\{(\w+)\}/g, (_, v) => vars[v] ?? "");
const v = (name) => `var(${name})`;
const $ = (sel) => document.querySelector(sel);
const fmt = (x, d = 0) => (x === null || x === undefined || Number.isNaN(x) ? "–" : Number(x).toFixed(d));
const signed = (x, d = 0) => (x === null || x === undefined ? "–" : (x > 0 ? "+" : "") + Number(x).toFixed(d));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
async function json(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}
function snapLabel(d) {
  const [y, m] = d.split("-");
  const extra = m === "05" ? " (pre-monsoon)" : m === "11" ? " (post-monsoon)" : "";
  return `${CYCLE_MONTH[m] || m} ${y}${extra}`;
}
function storage(k, val) {
  try {
    if (val === undefined) return localStorage.getItem(k);
    localStorage.setItem(k, val);
  } catch (e) { return null; }
}

// ---------------- record access (now or snapshot) ----------------
function record(lgd) {
  if (st.snapshot === "now") {
    const r = status.districts[lgd];
    if (!r) return null;
    return {
      quadrant: r.quadrant, provisional: r.provisional, why: r.why_none,
      rain: r.rain, gw: r.gw, stress: r.stress, idm: r.idm,
    };
  }
  const s = cache.snaps[st.snapshot];
  const row = s && s.districts[lgd];
  if (!row) return null;
  const f = Object.fromEntries(s.fields.map((k, i) => [k, row[i]]));
  const now = status.districts[lgd] || {};
  return {
    quadrant: f.quadrant ? QUAD[f.quadrant] : null,
    provisional: !!f.quadrant && f.gw_tier === "provisional",
    why: f.quadrant ? null : (f.rain_category ? `gw_${f.gw_tier}` : "no_rain_data"),
    rain: {
      category: f.rain_category, departure_pct: f.rain_dep_pct, source: f.rain_source,
      short_reasons: f.rain_short_reasons ? String(f.rain_short_reasons).split(",") : [],
      dry_spell_weeks: f.rain_dry_spell_weeks, spi_season: f.rain_spi_season,
    },
    gw: { tier: f.gw_tier, percentile: f.gw_percentile },
    stress: now.stress || {},
    idm: { class_of_mean: f.idm_class },
  };
}

// ---------------- colour per layer ----------------
function fillFor(lgd) {
  const r = record(lgd);
  if (!r) return "url(#nodata)";
  switch (st.layer) {
    case "quadrant": return r.quadrant ? v(QUAD_VAR[r.quadrant]) : "url(#nodata)";
    case "rain": return r.rain && RAIN_VAR[r.rain.category] ? v(RAIN_VAR[r.rain.category]) : "url(#nodata)";
    case "gw": {
      const g = r.gw || {};
      if (["full", "short", "provisional"].includes(g.tier) && g.percentile !== null && g.percentile !== undefined) {
        const p = g.percentile;
        return v(p < 10 ? "--sev-4" : p <= 20 ? "--sev-3" : p < 40 ? "--sev-1" : p < 60 ? "--sev-0" : "--neutral");
      }
      return g.tier === "level_only" ? v("--q-fine") : "url(#nodata)";
    }
    case "stress": return STRESS_VAR[r.stress?.category] ? v(STRESS_VAR[r.stress.category]) : "url(#nodata)";
    case "idm": return IDM_VAR[r.idm?.class_of_mean] ? v(IDM_VAR[r.idm.class_of_mean]) : "url(#nodata)";
  }
  return "url(#nodata)";
}
function opacityFor(lgd) {
  const r = record(lgd);
  return st.layer === "quadrant" && r && r.provisional ? 0.5 : (st.layer === "gw" && r?.gw?.tier === "provisional" ? 0.5 : 1);
}

// ---------------- map ----------------
function drawMap() {
  const svg = d3.select("#map");
  const W = 900, H = 1000;
  svg.attr("viewBox", `0 0 ${W} ${H}`);
  const defs = svg.append("defs");
  const pat = defs.append("pattern").attr("id", "nodata").attr("patternUnits", "userSpaceOnUse")
    .attr("width", 6).attr("height", 6).attr("patternTransform", "rotate(45)");
  pat.append("rect").attr("width", 6).attr("height", 6).style("fill", v("--surface"));
  pat.append("line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 6).style("stroke", v("--axis")).attr("stroke-width", 1.2);

  const proj = d3.geoConicEqualArea().parallels([12, 28]).rotate([-80, 0]).fitSize([W, H], geo);
  const path = d3.geoPath(proj);
  const g = svg.append("g");
  paths = g.selectAll("path.d").data(geo.features).join("path")
    .attr("class", "d").attr("d", path)
    .attr("data-lgd", (f) => f.properties.lgd)
    .style("pointer-events", (f) => (f.properties.lgd ? null : "none"))
    .on("mousemove", (ev, f) => showTip(ev, f))
    .on("mouseleave", hideTip)
    .on("click", (ev, f) => f.properties.lgd && select(f.properties.lgd));
  outlinePath = g.append("path").attr("class", "outline");
  json(DATA + "india_outline.geojson").then((o) => outlinePath.attr("d", path(o)));
  recolor();
}
function recolor() {
  paths.style("fill", (f) => (f.properties.lgd ? fillFor(f.properties.lgd) : "url(#nodata)"))
    .style("fill-opacity", (f) => (f.properties.lgd ? opacityFor(f.properties.lgd) : 1))
    .classed("sel", (f) => f.properties.lgd === st.selected);
  drawLegend();
}

function showTip(ev, f) {
  const lgd = f.properties.lgd;
  if (!lgd) return;
  const r = record(lgd);
  const tip = $("#tooltip");
  const wrap = $("#map-wrap").getBoundingClientRect();
  let line = "";
  if (r) {
    const q = r.quadrant ? t(`q_${r.quadrant}`) + (r.provisional ? ` (${t("panel_provisional")})` : "") : t("q_none");
    const rain = r.rain?.category ? `${t("panel_rain")}: ${t("rain_cat_" + r.rain.category)} (${signed(r.rain.departure_pct)}%)` : "";
    const gw = r.gw?.percentile !== null && r.gw?.percentile !== undefined ? `${t("panel_gw")}: ${t("gw_percentile").toLowerCase()} ${fmt(r.gw.percentile)}` : "";
    line = [q, rain, gw].filter(Boolean).map(esc).join("<br>");
  }
  tip.innerHTML = `<b>${esc(f.properties.n)}, ${esc(f.properties.s)}</b>${line}`;
  tip.style.display = "block";
  const x = ev.clientX - wrap.left + 14, y = ev.clientY - wrap.top + 14;
  tip.style.left = Math.min(x, wrap.width - 270) + "px";
  tip.style.top = y + "px";
}
function hideTip() { $("#tooltip").style.display = "none"; }

// ---------------- legend ----------------
function swatch(fill, op = 1) { return `<span class="sw" style="background:${fill};opacity:${op}"></span>`; }
const NODATA_SW = `<span class="sw" style="background:repeating-linear-gradient(45deg,var(--surface) 0 3px,var(--axis) 3px 4px)"></span>`;
function drawLegend() {
  const L = $("#legend");
  let h = `<h4>${esc(t("layer_" + st.layer))}</h4>`;
  if (st.layer === "quadrant") {
    const cell = (q, light) => `<div class="cell${light ? " light-text" : ""}" style="background:${v(QUAD_VAR[q])}" title="${esc(t("q_" + q + "_desc"))}">${esc(t("q_" + q))}</div>`;
    h += `<div class="quad-grid">
      <span></span><span class="hd">${esc(t("legend_gw_ok"))}</span><span class="hd">${esc(t("legend_gw_low"))}</span>
      <span class="hd">${esc(t("legend_rain_ok"))}</span>${cell("fine", true)}${cell("hidden_drought")}
      <span class="hd">${esc(t("legend_rain_short"))}</span>${cell("buffered", true)}${cell("double_drought")}
    </div>
    <div class="note">${esc(t("legend_provisional"))}</div>
    <div class="row">${NODATA_SW}${esc(t("legend_none"))}</div>`;
  } else {
    const rows = {
      rain: Object.entries(RAIN_VAR).map(([k, c]) => [v(c), t("rain_cat_" + k)]),
      gw: [["--neutral", "gw_bucket_60"], ["--sev-0", "gw_bucket_40"], ["--sev-1", "gw_bucket_20"], ["--sev-3", "gw_bucket_10"], ["--sev-4", "gw_bucket_0"], ["--q-fine", "gw_level_only"]].map(([c, k]) => [v(c), t(k)]),
      stress: Object.entries(STRESS_VAR).map(([k, c]) => [v(c), t("stress_" + k)]),
      idm: Object.entries(IDM_VAR).map(([k, c]) => [v(c), t("idm_" + k)]),
    }[st.layer];
    h += rows.map(([c, label]) => `<div class="row">${swatch(c)}${esc(label)}</div>`).join("");
    if (st.layer === "gw") h += `<div class="note">${esc(t("legend_provisional"))}</div>`;
    h += `<div class="row">${NODATA_SW}${esc(t("no_data"))}</div>`;
  }
  L.innerHTML = h;
}

// ---------------- selection + panel ----------------
function select(lgd) {
  st.selected = lgd;
  recolor();
  renderPanel();
  if (window.matchMedia("(max-width: 900px)").matches) $("#panel").scrollIntoView({ behavior: "smooth" });
}

function reasonText(reasons, r) {
  return (reasons || []).map((k) => t("reason_" + k, { n: r.dry_spell_weeks })).join("; ");
}

async function renderPanel() {
  const P = $("#panel");
  if (!st.selected) { P.innerHTML = `<p class="empty">${esc(t("panel_hint"))}</p>`; return; }
  const lgd = st.selected;
  const r = record(lgd) || {};
  const nm = names[lgd];
  const q = r.quadrant;
  const chip = q
    ? `<span class="chip"><span class="dot" style="background:${v(QUAD_VAR[q])};opacity:${r.provisional ? 0.5 : 1}"></span>${esc(t("q_" + q))}</span>
       ${r.provisional ? `<span class="badge">${esc(t("panel_provisional"))}</span>` : ""}
       <p class="explain">${esc(t("q_" + q + "_desc"))}</p>`
    : `<span class="chip"><span class="dot" style="background:var(--axis)"></span>${esc(t("q_none"))}</span>
       ${r.why ? `<p class="explain">${esc(t("why_" + r.why))}</p>` : ""}`;

  const rain = r.rain || {};
  const rainHtml = rain.category ? `
    <dl class="kv">
      ${rain.season ? `<dt>${esc(t("season_" + rain.season))}</dt><dd>${esc(rain.start || "")} – ${esc(rain.end || "")}</dd>` : ""}
      <dt>${esc(t("rain_departure"))}</dt><dd>${signed(rain.departure_pct)}%</dd>
      <dt>${esc(t("rain_category"))}</dt><dd>${esc(t("rain_cat_" + rain.category))}</dd>
      <dt>${esc(t("rain_dry_spell"))}</dt><dd>${rain.dry_spell_weeks === null || rain.dry_spell_weeks === undefined ? "–" : esc(t("weeks", { n: rain.dry_spell_weeks }))}</dd>
      <dt>${esc(t("rain_spi"))}</dt><dd>${fmt(rain.spi_season, 2)}</dd>
      <dt>${esc(t("rain_source"))}</dt><dd>${esc(t("src_" + rain.source))}</dd>
    </dl>
    ${rain.short_reasons && rain.short_reasons.length ? `<p class="explain">${esc(t("rain_reasons"))}: ${esc(reasonText(rain.short_reasons, rain))}.</p>` : ""}`
    : `<p class="empty">${esc(t("no_data"))}</p>`;

  const gw = r.gw || {};
  const gwHtml = `
    <dl class="kv">
      <dt>${esc(t("gw_tier"))}</dt><dd>${esc(t("tier_" + (gw.tier || "insufficient")))}</dd>
      ${gw.percentile !== null && gw.percentile !== undefined ? `<dt>${esc(t("gw_percentile"))}</dt><dd>${fmt(gw.percentile)}</dd>` : ""}
      ${gw.median_depth_m !== undefined && gw.median_depth_m !== null ? `<dt>${esc(t("gw_depth"))}</dt><dd>${fmt(gw.median_depth_m, 1)} ${t("m")}</dd>` : ""}
      ${gw.change_vs_last_year_m !== undefined && gw.change_vs_last_year_m !== null ? `<dt>${esc(t("gw_vs_ly"))}</dt><dd>${signed(gw.change_vs_last_year_m, 2)} ${t("m")} (${t(gw.change_vs_last_year_m >= 0 ? "rose" : "fell")})</dd>` : ""}
      ${gw.vs_decadal_mean_m !== undefined && gw.vs_decadal_mean_m !== null ? `<dt>${esc(t("gw_vs_10y"))}</dt><dd>${signed(gw.vs_decadal_mean_m, 2)} ${t("m")}</dd>` : ""}
      ${gw.n_live !== undefined ? `<dt>${esc(t("gw_wells"))}</dt><dd>${fmt(gw.n_live)}</dd>` : ""}
      <dt>${esc(t("gw_trend"))}</dt><dd id="gw-trend">…</dd>
    </dl>
    ${gw.percentile !== null && gw.percentile !== undefined ? `<p class="explain">${esc(t("gw_percentile_explain", { p: fmt(gw.percentile), d: fmt(100 - gw.percentile) }))}</p>` : ""}
    <div class="chart" id="gw-chart"></div>`;

  const s = r.stress || {};
  const stressHtml = s.status === "not_in_ingres" || !s.status ? `<p class="empty">${esc(t("stress_not_in"))}</p>` : `
    <dl class="kv">
      <dt>${esc(t("stress_category"))}</dt><dd>${esc(s.category ? t("stress_" + s.category) : t("stress_none"))}</dd>
      <dt>${esc(t("stress_stage"))}</dt><dd>${fmt(s.stage_pct, 1)}%</dd>
      ${s.worst_unit ? `<dt>${esc(t("stress_worst"))}</dt><dd>${esc(s.worst_unit.name)}: ${esc(t("stress_" + s.worst_unit.category))} (${fmt(s.worst_unit.stage_pct, 1)}%)</dd>` : ""}
    </dl>
    ${s.hidden_stress ? `<p class="explain">${esc(t("stress_hidden"))}</p>` : ""}`;

  const idm = r.idm || {};
  const idmHtml = idm.class_of_mean ? `
    <dl class="kv"><dt>${esc(t("idm_class"))}</dt><dd>${esc(t("idm_" + idm.class_of_mean))}</dd></dl>
    <div class="chart" id="idm-chart"></div>` : `<p class="empty">${esc(t("no_data"))}</p>`;

  P.innerHTML = `
    <h2>${esc(nm?.n || lgd)}</h2>
    <p class="sub">${esc(nm?.s || "")} · LGD ${lgd}${st.snapshot !== "now" ? " · " + esc(snapLabel(st.snapshot)) : ""}</p>
    <section><h3>${esc(t("panel_category"))}</h3>${chip}</section>
    <section><h3>${esc(t("panel_rain"))}</h3>${rainHtml}</section>
    <section><h3>${esc(t("panel_gw"))}</h3>${gwHtml}</section>
    <section><h3>${esc(t("panel_stress"))}</h3>${stressHtml}</section>
    <section><h3>${esc(t("panel_idm"))}</h3>${idmHtml}</section>
    <section><h3>${esc(t("panel_history"))}</h3><div id="timeline">${esc(t("loading"))}</div></section>`;

  // lazy extras
  loadGwHistory().then((h) => {
    const d = h.districts[lgd] || {};
    $("#gw-trend") && ($("#gw-trend").textContent = d.trend_pre_m_per_yr === undefined ? "–" :
      t("gw_trend_val", { v: fmt(Math.abs(d.trend_pre_m_per_yr), 2), dir: t(d.trend_pre_m_per_yr > 0 ? "falling" : "rising"), n: d.trend_wells, s: fmt(d.share_wells_falling * 100) }));
    if (d.PRE || d.NOV) gwChart($("#gw-chart"), d);
  });
  if (idm.class_of_mean && st.snapshot === "now") loadIdm().then((x) => {
    const d = x.districts[lgd];
    if (d && $("#idm-chart")) idmChart($("#idm-chart"), d.d1plus_last26, x.weeks_in_series);
  });
  loadDistrictHistory(lgd).then((h) => timeline($("#timeline"), h)).catch(() => { $("#timeline").textContent = t("no_data"); });
}

let gwHistP, idmP;
const loadGwHistory = () => (gwHistP ||= json(DATA + "gw_history.json"));
const loadIdm = () => (idmP ||= json(DATA + "idm.json"));
async function loadDistrictHistory(lgd) {
  if (!cache.dist[lgd]) cache.dist[lgd] = await json(`${DATA}history/d_${lgd}.json`);
  return cache.dist[lgd];
}

// ---------------- charts ----------------
function chartTip(container) {
  let tip = container.querySelector(".tooltip");
  if (!tip) { tip = document.createElement("div"); tip.className = "tooltip"; container.style.position = "relative"; container.appendChild(tip); }
  return tip;
}

function gwChart(el, d) {
  const series = [["PRE", t("gw_pre"), "--series-1"], ["NOV", t("gw_nov"), "--series-2"]]
    .filter(([k]) => d[k])
    .map(([k, label, c]) => ({ key: k, label, color: v(c), pts: Object.entries(d[k]).map(([y, [a, n]]) => ({ y: +y, v: -a, n })).sort((p, q) => p.y - q.y) }));
  if (!series.length) return;
  const W = 360, H = 170, m = { t: 22, r: 70, b: 22, l: 34 };
  const all = series.flatMap((s) => s.pts);
  const x = d3.scaleLinear().domain(d3.extent(all, (p) => p.y)).range([m.l, W - m.r]);
  const ext = d3.max(all, (p) => Math.abs(p.v)) || 1;
  const y = d3.scaleLinear().domain([-ext, ext]).nice().range([H - m.b, m.t]);
  el.innerHTML = `<div class="explain" style="margin:0 0 2px">${esc(t("gw_chart_title"))}</div>`;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  svg.append("g").attr("class", "grid").selectAll("line").data(y.ticks(4)).join("line")
    .attr("x1", m.l).attr("x2", W - m.r).attr("y1", y).attr("y2", y);
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(5).tickFormat(d3.format("d")).tickSizeOuter(0));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickSizeOuter(0));
  svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y(0)).attr("y2", y(0)).style("stroke", v("--axis"));
  const line = d3.line().x((p) => x(p.y)).y((p) => y(p.v)).defined((p) => p.v !== null);
  for (const s of series) svg.append("path").attr("class", "line").attr("d", line(s.pts)).style("stroke", s.color);
  // direct labels at line ends, nudged apart so they never overlap (min 12px)
  const ends = series.map((s) => ({ s, last: s.pts[s.pts.length - 1] })).map((e) => ({ ...e, ly: y(e.last.v) }))
    .sort((a, b) => a.ly - b.ly);
  for (let i = 1; i < ends.length; i++) if (ends[i].ly - ends[i - 1].ly < 12) ends[i].ly = ends[i - 1].ly + 12;
  for (const e of ends) {
    svg.append("text").attr("x", x(e.last.y) + 6).attr("y", e.ly + 3).text(e.s.label)
      .style("fill", v("--ink-2")).style("font-size", "10px");
  }
  const cross = svg.append("line").attr("y1", m.t).attr("y2", H - m.b).style("stroke", v("--axis")).style("display", "none");
  const tip = chartTip(el);
  svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b)
    .style("fill", "transparent")
    .on("mousemove", (ev) => {
      const [mx] = d3.pointer(ev);
      const yr = Math.round(x.invert(mx));
      cross.style("display", null).attr("x1", x(yr)).attr("x2", x(yr));
      const rows = series.map((s) => { const p = s.pts.find((q) => q.y === yr); return p ? `${esc(s.label)}: ${signed(p.v, 2)} m (${p.n} wells)` : null; }).filter(Boolean);
      tip.innerHTML = `<b>${yr}</b>${rows.join("<br>") || esc(t("no_data"))}`;
      tip.style.display = "block";
      const bb = el.getBoundingClientRect();
      tip.style.left = Math.min(ev.clientX - bb.left + 10, bb.width - 200) + "px";
      tip.style.top = ev.clientY - bb.top + 10 + "px";
    })
    .on("mouseleave", () => { cross.style("display", "none"); tip.style.display = "none"; });
  const lg = document.createElement("div");
  lg.className = "chart-legend";
  lg.innerHTML = series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.label)}</span>`).join("");
  el.appendChild(lg);
}

function idmChart(el, vals, weeks) {
  const W = 360, H = 110, m = { t: 14, r: 10, b: 20, l: 30 };
  const pts = vals.map((val, i) => ({ i, val, w: weeks[i] }));
  const x = d3.scaleLinear().domain([0, pts.length - 1]).range([m.l, W - m.r]);
  const y = d3.scaleLinear().domain([0, 100]).range([H - m.b, m.t]);
  el.innerHTML = `<div class="explain" style="margin:0 0 2px">${esc(t("idm_chart_title"))}</div>`;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  svg.append("g").attr("class", "grid").selectAll("line").data([0, 50, 100]).join("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y).attr("y2", y);
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).tickValues([0, 50, 100]).tickFormat((d) => d + "%").tickSizeOuter(0));
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
    .call(d3.axisBottom(x).tickValues([0, pts.length - 1]).tickFormat((i) => pts[i]?.w?.slice(5) || "").tickSizeOuter(0));
  svg.append("path").attr("class", "line").attr("d", d3.line().x((p) => x(p.i)).y((p) => y(p.val))(pts)).style("stroke", v("--series-1"));
  const dot = svg.append("circle").attr("r", 4).style("fill", v("--series-1")).style("stroke", v("--surface")).attr("stroke-width", 2).style("display", "none");
  const tip = chartTip(el);
  svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b).style("fill", "transparent")
    .on("mousemove", (ev) => {
      const i = Math.max(0, Math.min(pts.length - 1, Math.round(x.invert(d3.pointer(ev)[0]))));
      dot.style("display", null).attr("cx", x(i)).attr("cy", y(pts[i].val));
      tip.innerHTML = `<b>${esc(pts[i].w)}</b>${fmt(pts[i].val, 1)}%`;
      tip.style.display = "block";
      const bb = el.getBoundingClientRect();
      tip.style.left = Math.min(ev.clientX - bb.left + 10, bb.width - 140) + "px";
      tip.style.top = ev.clientY - bb.top + 10 + "px";
    })
    .on("mouseleave", () => { dot.style("display", "none"); tip.style.display = "none"; });
}

function timeline(el, h) {
  const fi = Object.fromEntries(h.fields.map((k, i) => [k, i]));
  const cells = h.rows.map((r) => {
    const q = r[fi.quadrant] ? QUAD[r[fi.quadrant]] : null;
    const prov = q && r[fi.gw_tier] === "provisional";
    const label = `${snapLabel(r[fi.snapshot])}: ${q ? t("q_" + q) + (prov ? ` (${t("panel_provisional")})` : "") : t("q_none")}`;
    const bg = q ? v(QUAD_VAR[q]) : "repeating-linear-gradient(45deg,var(--surface) 0 2px,var(--axis) 2px 3px)";
    return `<span title="${esc(label)}" aria-label="${esc(label)}" style="background:${bg};opacity:${prov ? 0.5 : 1}"></span>`;
  });
  const first = h.rows[0]?.[fi.snapshot]?.slice(0, 4), last = h.rows[h.rows.length - 1]?.[fi.snapshot]?.slice(0, 4);
  el.innerHTML = `<div class="timeline">${cells.join("")}</div><div class="timeline-years"><span>${first || ""}</span><span>${last || ""}</span></div>`;
}

// ---------------- table view ----------------
// why rain counted as short, beyond the IMD category (dry spell / SPI)
function rainWhy(rain) {
  const extra = (rain.short_reasons || []).filter((k) => k !== "deviation")
    .map((k) => k === "dry_spell" ? t("short_dry_spell", { n: rain.dry_spell_weeks }) : t("short_spi", { v: fmt(rain.spi_season, 1) }));
  return extra.length ? " · " + extra.join(", ") : "";
}
function tableRows() {
  return geo.features.filter((f) => f.properties.lgd).map((f) => {
    const lgd = f.properties.lgd, r = record(lgd) || {};
    return {
      lgd, district: f.properties.n, state: f.properties.s,
      category: r.quadrant ? t("q_" + r.quadrant) + (r.provisional ? "*" : "") : "",
      quadrant: r.quadrant || "none",
      rank: { double_drought: 0, hidden_drought: 1, buffered: 2, fine: 3 }[r.quadrant] ?? 4,
      rain: r.rain?.category ? t("rain_cat_" + r.rain.category) + rainWhy(r.rain) : "",
      rain_dep: r.rain?.departure_pct ?? null,
      gw_pct: r.gw?.percentile ?? null,
      gw_tier: r.gw?.tier ? t("tier_" + r.gw.tier) : "",
      stress: r.stress?.category ? t("stress_" + r.stress.category) : "",
      idm: r.idm?.class_of_mean ? t("idm_" + r.idm.class_of_mean) : "",
    };
  });
}
const COLS = [["district", "col_district"], ["state", "col_state"], ["category", "col_category"], ["rain", "col_rain"],
  ["rain_dep", "col_rain_dep", true], ["gw_pct", "col_gw_pct", true], ["gw_tier", "col_gw_tier"], ["stress", "col_stress"], ["idm", "col_idm"]];
function renderTable() {
  const tools = $("#table-tools");
  const qs = ["hidden_drought", "double_drought", "buffered", "fine", "none"];
  tools.innerHTML = `<strong>${esc(t("table_title"))}</strong>
    <button class="filter-chip" data-q="" aria-pressed="${!st.filter}">${esc(t("table_all"))}</button>
    ${qs.map((q) => `<button class="filter-chip" data-q="${q}" aria-pressed="${st.filter === q}">${esc(t(q === "none" ? "q_none" : "q_" + q))}</button>`).join("")}
    <button class="btn" id="dl">${esc(t("table_download"))}</button>`;
  tools.querySelectorAll(".filter-chip").forEach((b) => b.onclick = () => { st.filter = b.dataset.q || null; renderTable(); });
  let rows = tableRows();
  if (st.filter) rows = rows.filter((r) => r.quadrant === st.filter);
  const [k, dir] = st.sort;
  const key = k === "category" ? "rank" : k;  // category sorts by severity, not alphabetically
  rows.sort((a, b) => {
    const x = a[key], y = b[key];
    if (x === null || x === "") return 1;
    if (y === null || y === "") return -1;
    return (typeof x === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
  });
  $("#table").innerHTML = `<thead><tr>${COLS.map(([c, lab]) => `<th data-k="${c}" aria-sort="${k === c ? (dir > 0 ? "ascending" : "descending") : "none"}">${esc(t(lab))}${k === c ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr data-lgd="${r.lgd}">${COLS.map(([c, , num]) => `<td class="${num ? "num" : ""}">${esc(r[c] === null ? "–" : num ? (c === "rain_dep" ? signed(r[c]) : fmt(r[c])) : r[c])}</td>`).join("")}</tr>`).join("")}</tbody>`;
  $("#table").querySelectorAll("th").forEach((th) => th.onclick = () => {
    st.sort = [th.dataset.k, st.sort[0] === th.dataset.k ? -st.sort[1] : 1];
    renderTable();
  });
  $("#table").querySelectorAll("tbody tr").forEach((tr) => tr.onclick = () => { setView("map"); select(+tr.dataset.lgd); });
  $("#dl").onclick = () => {
    const head = COLS.map(([, lab]) => t(lab)).concat(["LGD", "date"]);
    const lines = [head].concat(rows.map((r) => COLS.map(([c]) => r[c] ?? "").concat([r.lgd, st.snapshot === "now" ? status.as_of.rain : st.snapshot])));
    const csv = lines.map((l) => l.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `drought-watch-${st.snapshot === "now" ? "latest" : st.snapshot}.csv`;
    a.click();
  };
}
function setView(view) {
  st.view = view;
  $("#map-view").hidden = view !== "map";
  $("#table-view").hidden = view !== "table";
  $("#nav-map").setAttribute("aria-pressed", view === "map");
  $("#nav-table").setAttribute("aria-pressed", view === "table");
  if (view === "table") renderTable();
}

// ---------------- controls ----------------
function asofLine() {
  if (st.snapshot === "now") {
    const a = status.as_of;
    $("#asof").textContent = t("asof_line", { rain: a.rain, gw: a.groundwater_cycle, idm: a.idm_week });
  } else {
    $("#asof").textContent = t("snapshot_note", { date: snapLabel(st.snapshot) });
  }
}
async function setSnapshot(d) {
  if (d !== "now" && !cache.snaps[d]) cache.snaps[d] = await json(`${DATA}history/s_${d}.json`);
  st.snapshot = d;
  asofLine();
  recolor();
  renderPanel();
  if (st.view === "table") renderTable();
}

function initControls() {
  const layer = $("#layer");
  layer.innerHTML = LAYERS.map((l) => `<option value="${l}">${esc(t("layer_" + l))}</option>`).join("");
  layer.onchange = () => { st.layer = layer.value; recolor(); };
  const date = $("#date");
  const snaps = [...histIndex.snapshots].reverse();
  date.innerHTML = `<option value="now">${esc(t("date_now"))}</option>` +
    snaps.map((d) => `<option value="${d}">${esc(snapLabel(d))} · ${histIndex.classified[d]} districts</option>`).join("");
  date.onchange = () => setSnapshot(date.value);
  const dl = $("#district-list");
  const list = geo.features.filter((f) => f.properties.lgd).map((f) => `${f.properties.n}, ${f.properties.s}`);
  dl.innerHTML = list.map((x) => `<option value="${esc(x)}">`).join("");
  $("#search").setAttribute("placeholder", t("search_placeholder"));
  $("#search").onchange = (e) => {
    const f = geo.features.find((g) => `${g.properties.n}, ${g.properties.s}` === e.target.value);
    if (f) { setView("map"); select(f.properties.lgd); }
  };
  $("#nav-map").onclick = () => setView("map");
  $("#nav-table").onclick = () => setView("table");
  $("#theme").onclick = () => {
    const cur = document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    storage("theme", next);
  };
}

// ---------------- boot ----------------
async function main() {
  const saved = storage("theme");
  if (saved) document.documentElement.dataset.theme = saved;
  S = await json("i18n/en.json");
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  [geo, status, histIndex] = await Promise.all([json(DATA + "districts.geojson"), json(DATA + "status.json"), json(DATA + "history/index.json")]);
  for (const f of geo.features) if (f.properties.lgd) names[f.properties.lgd] = { n: f.properties.n, s: f.properties.s };
  initControls();
  asofLine();
  drawMap();
  const want = new URLSearchParams(location.search).get("d");
  if (want && names[want]) select(+want); else renderPanel();
}
main().catch((e) => { document.body.insertAdjacentHTML("beforeend", `<p style="padding:16px;color:#d03b3b">Failed to load: ${esc(e.message)}</p>`); });
