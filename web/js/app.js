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
const st = { layer: "quadrant", snapshot: "now", selected: null, view: "map", filter: null, sort: ["category", 1],
  groups: new Set(LAYERS), q: "" };  // table: column groups shown, district search text
const cache = { snaps: {}, dist: {} };
let geo, status, histIndex, names = {}, paths, outlinePath, zoom;

// ---------------- helpers ----------------
const t = (k, vars = {}) => (S && S[k] !== undefined ? S[k] : k).replace(/\{(\w+)\}/g, (_, v) => vars[v] ?? "");
const v = (name) => `var(${name})`;
const $ = (sel) => document.querySelector(sel);
const fmt = (x, d = 0) => (x === null || x === undefined || Number.isNaN(x) ? "–" : Number(x).toFixed(d));
const signed = (x, d = 0) => (x === null || x === undefined ? "–" : (x > 0 ? "+" : "") + Number(x).toFixed(d));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
async function json(path) {
  const r = await fetch(path, { cache: "no-cache" });
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
function record(lgd, snap = st.snapshot) {
  if (snap === "now") {
    const r = status.districts[lgd];
    if (!r) return null;
    return {
      quadrant: r.quadrant, provisional: r.provisional, why: r.why_none,
      rain: r.rain, gw: r.gw, stress: { ...r.stress, edition: "2025-2026" }, idm: r.idm,
    };
  }
  const s = cache.snaps[snap];
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
    gw: { tier: f.gw_tier, percentile: f.gw_percentile, median_depth_m: f.gw_median_depth_m,
          change_vs_last_year_m: f.gw_change_vs_ly_m, vs_decadal_mean_m: f.gw_vs_10y_m, n_live: f.gw_wells },
    stress: f.stress_edition
      ? { category: f.stress_category, stage_pct: f.stress_stage_pct, edition: f.stress_edition,
          status: f.stress_category || f.stress_stage_pct !== null ? "assessed" : "not_in_ingres" }
      : { status: "no_edition" },
    idm: { class_of_mean: f.idm_class, cdi_mean: f.idm_cdi_mean, pct_in_drought_d0plus: f.idm_d0plus_pct },
  };
}

// ---------------- why no data (short, per layer) ----------------
function noDataReason(r) {
  if (!r) return t("why_no_rain_data");
  switch (st.layer) {
    case "quadrant": return r.why ? t("why_" + r.why) : "";
    case "rain": return t("why_no_rain_data");
    case "gw": return r.gw?.tier === "level_only" ? t("why_gw_level_only") : t("why_gw_insufficient");
    case "stress":
      if (r.stress?.status === "no_edition") return t("stress_unavailable");
      return t("stress_not_in");
    case "idm":
      if (st.snapshot !== "now" && st.snapshot < "2021-07-14") return t("idm_unavailable");
      return t("why_idm_none");
  }
  return "";
}
function layerHasData(lgd) { return fillFor(lgd) !== "url(#nodata)"; }
// Shown at the top of the panel when the map layer has nothing for the selected district,
// so it is clear why the map is hatched while other sections below still have figures.
const LAYER_PANEL = { rain: "panel_rain", gw: "panel_gw", stress: "panel_stress", idm: "panel_idm" };
function panelNotice(lgd, r) {
  if (layerHasData(lgd)) return "";
  const has = {
    rain: !!r.rain?.category,
    gw: (r.gw?.percentile ?? r.gw?.median_depth_m ?? null) !== null,
    stress: !!r.stress?.category || (r.stress?.stage_pct ?? null) !== null,
    idm: !!r.idm?.class_of_mean,
  };
  const others = Object.keys(LAYER_PANEL).filter((k) => k !== st.layer && has[k]).map((k) => t(LAYER_PANEL[k]).toLowerCase());
  const why = noDataReason(r).replace(/\.$/, "");
  return `<p class="notice"><b>${esc(t("notice_no_layer", { layer: t("layer_" + st.layer) }))}</b>
    ${why ? esc(why[0].toUpperCase() + why.slice(1)) + ". " : ""}${esc(others.length ? t("notice_others", { list: others.join(", ") }) : t("notice_no_others"))}</p>`;
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
  // Zoom: buttons, drag, double-click, pinch. Plain scroll and one-finger swipes are left to
  // the page (wheel needs Ctrl/Cmd, which is also what a trackpad pinch sends).
  zoom = d3.zoom().scaleExtent([1, 12]).translateExtent([[0, 0], [W, H]])
    .filter((ev) => ev.type === "wheel" ? ev.ctrlKey || ev.metaKey
      : ev.type.startsWith("touch") ? ev.touches.length > 1 || d3.zoomTransform(svg.node()).k > 1
      : !ev.button)
    .on("zoom", (ev) => { g.attr("transform", ev.transform); hideTip(); });
  svg.call(zoom);
  const zoomBy = (k) => svg.transition().duration(200).call(zoom.scaleBy, k);
  for (const [id, key, fn] of [["#zoom-in", "zoom_in", () => zoomBy(1.6)], ["#zoom-out", "zoom_out", () => zoomBy(1 / 1.6)],
    ["#zoom-reset", "zoom_reset", () => svg.transition().duration(200).call(zoom.transform, d3.zoomIdentity)]]) {
    $(id).onclick = fn;
    $(id).title = t(key);
    $(id).setAttribute("aria-label", t(key));
  }
  recolor();
}
function layerNotice() {
  let n = $("#layer-notice");
  if (!n) { n = document.createElement("div"); n.id = "layer-notice"; n.className = "layer-notice"; $("#map-wrap").appendChild(n); }
  const any = geo.features.some((f) => f.properties.lgd && layerHasData(f.properties.lgd));
  let msg = "";
  if (st.moved) {
    msg = t("date_moved", { layer: t("layer_" + st.layer), date: snapLabel(st.moved) });
  } else if (!any) {
    msg = st.layer === "idm" ? t("idm_unavailable") : st.layer === "stress" ? t("stress_unavailable") : t("layer_empty");
  }
  n.textContent = msg;
  n.hidden = !msg;
}
function recolor() {
  paths.style("fill", (f) => (f.properties.lgd ? fillFor(f.properties.lgd) : "url(#nodata)"))
    .style("fill-opacity", (f) => (f.properties.lgd ? opacityFor(f.properties.lgd) : 1))
    .classed("sel", (f) => f.properties.lgd === st.selected);
  drawLegend();
  layerNotice();
}

function showTip(ev, f) {
  const lgd = f.properties.lgd;
  if (!lgd) return;
  const r = record(lgd);
  const tip = $("#tooltip");
  const wrap = $("#map-wrap").getBoundingClientRect();
  let line = "";
  if (r) {
    const q = r.quadrant ? t(`q_${r.quadrant}`) + (r.provisional ? ` (${t("panel_provisional")})` : "") : t("q_none") + ": " + t("why_" + (r.why || "no_rain_data"));
    const rain = r.rain?.category ? `${t("panel_rain")}: ${t("rain_cat_" + r.rain.category)} (${signed(r.rain.departure_pct)}%)` : "";
    const gw = r.gw?.percentile !== null && r.gw?.percentile !== undefined ? `${t("panel_gw")}: ${t("gw_percentile").toLowerCase()} ${fmt(r.gw.percentile)}` : "";
    line = [q, rain, gw].filter(Boolean).map(esc).join("<br>");
  }
  const layerNote = st.layer !== "quadrant" && !layerHasData(lgd) ? `<br><em>${esc(t("layer_" + st.layer))}: ${esc(t("no_data"))} (${esc(noDataReason(r))})</em>` : "";
  tip.innerHTML = `<b>${esc(f.properties.n)}, ${esc(f.properties.s)}</b>${line}${layerNote}`;
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
  $("#search").value = names[lgd] ? `${names[lgd].n}, ${names[lgd].s}` : "";
  recolor();
  renderPanel();
  if (window.matchMedia("(max-width: 900px)").matches) $("#panel").scrollIntoView({ behavior: "smooth" });
}

function reasonText(reasons, r) {
  return (reasons || []).map((k) => t("reason_" + k, { n: r.dry_spell_weeks })).join("; ");
}

async function renderPanel() {
  const P = $("#panel");
  P.classList.toggle("is-empty", !st.selected);
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
    : `<p class="empty">${esc(t("no_data"))}: ${esc(t("why_no_rain_data"))}</p>`;

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
  const stressHtml = s.status === "no_edition" ? `<p class="empty">${esc(t("stress_unavailable"))}</p>`
    : s.status === "not_in_ingres" || !s.status ? `<p class="empty">${esc(t("stress_not_in"))}</p>` : `
    <dl class="kv">
      <dt>${esc(t("stress_edition"))}</dt><dd>IN-GRES ${esc(s.edition || "")}</dd>
      <dt>${esc(t("stress_category"))}</dt><dd>${esc(s.category ? t("stress_" + s.category) : t("stress_none"))}</dd>
      <dt>${esc(t("stress_stage"))}</dt><dd>${fmt(s.stage_pct, 1)}%</dd>
      ${s.worst_unit ? `<dt>${esc(t("stress_worst"))}</dt><dd>${esc(s.worst_unit.name)}: ${esc(t("stress_" + s.worst_unit.category))} (${fmt(s.worst_unit.stage_pct, 1)}%)</dd>` : ""}
    </dl>
    ${s.hidden_stress ? `<p class="explain">${esc(t("stress_hidden"))}</p>` : ""}`;

  const idm = r.idm || {};
  const idmHtml = !idm.class_of_mean ? `<p class="empty">${esc(t("no_data"))}: ${esc(st.snapshot !== "now" && st.snapshot < "2021-07-14" ? t("idm_unavailable") : t("why_idm_none"))}</p>` : `
    <dl class="kv"><dt>${esc(t("idm_class"))}</dt><dd>${esc(t("idm_" + idm.class_of_mean))}</dd></dl>
    <div class="chart" id="idm-chart"></div>`;

  P.innerHTML = `
    <h2>${esc(nm?.n || lgd)}</h2>
    <p class="sub">${esc(nm?.s || "")} · LGD ${lgd}${st.snapshot !== "now" ? " · " + esc(snapLabel(st.snapshot)) : ""}</p>
    ${panelNotice(lgd, r)}
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
function tableRows(snap = st.snapshot) {
  return geo.features.filter((f) => f.properties.lgd).map((f) => {
    const lgd = f.properties.lgd, r = record(lgd, snap) || {};
    const rain = r.rain || {}, gw = r.gw || {}, s = r.stress || {}, idm = r.idm || {};
    return {
      lgd, district: f.properties.n, state: f.properties.s,
      category: r.quadrant ? t("q_" + r.quadrant) + (r.provisional ? " (" + t("panel_provisional") + ")" : "") : t("q_none"),
      quadrant: r.quadrant || "none",
      rank: { double_drought: 0, hidden_drought: 1, buffered: 2, fine: 3 }[r.quadrant] ?? 4,
      rain: rain.category ? t("rain_cat_" + rain.category) + rainWhy(rain) : "",
      rain_dep: rain.departure_pct ?? null, rain_spi: rain.spi_season ?? null, rain_dry: rain.dry_spell_weeks ?? null,
      rain_src: rain.source ? t("src_short_" + rain.source) : "",
      gw_pct: gw.percentile ?? null, gw_tier: gw.tier ? t("tier_" + gw.tier) : "",
      gw_depth: gw.median_depth_m ?? null, gw_ly: gw.change_vs_last_year_m ?? null, gw_10y: gw.vs_decadal_mean_m ?? null,
      gw_wells: gw.n_live ?? null,
      stress: s.category ? t("stress_" + s.category) : "", stress_stage: s.stage_pct ?? null,
      stress_ed: s.category || (s.stage_pct ?? null) !== null ? s.edition || "" : "",
      idm: idm.class_of_mean ? t("idm_" + idm.class_of_mean) : "",
      idm_cdi: idm.cdi_mean ?? null, idm_area: idm.pct_in_drought_d0plus ?? null,
    };
  });
}
// Table columns: [key, label, group, decimals (numeric columns only), show + sign].
// The "Columns" chips in the ribbon switch whole groups on and off; district and state always show.
const COLS = [
  ["district", "col_district", "id"], ["state", "col_state", "id"],
  ["category", "col_category", "quadrant"],
  ["rain", "col_rain", "rain"], ["rain_dep", "col_rain_dep", "rain", 0, true], ["rain_spi", "col_rain_spi", "rain", 2, true],
  ["rain_dry", "col_rain_dry", "rain", 0], ["rain_src", "col_rain_src", "rain"],
  ["gw_pct", "col_gw_pct", "gw", 0], ["gw_tier", "col_gw_tier", "gw"], ["gw_depth", "col_gw_depth", "gw", 1],
  ["gw_ly", "col_gw_ly", "gw", 2, true], ["gw_10y", "col_gw_10y", "gw", 2, true], ["gw_wells", "col_gw_wells", "gw", 0],
  ["stress", "col_stress", "stress"], ["stress_stage", "col_stress_stage", "stress", 1], ["stress_ed", "col_stress_ed", "stress"],
  ["idm", "col_idm", "idm"], ["idm_cdi", "col_idm_cdi", "idm", 2, true], ["idm_area", "col_idm_area", "idm", 1],
];
const GROUP_HELP = { quadrant: "#categories", rain: "#rain", gw: "#groundwater", stress: "#stress", idm: "#drought-index" };
const shownCols = () => COLS.filter(([, , g]) => g === "id" || st.groups.has(g));
const snapDate = (snap) => (snap === "now" ? status.as_of.rain : snap);
function filterSort(rows) {
  if (st.filter) rows = rows.filter((r) => r.quadrant === st.filter);
  const q = st.q.trim().toLowerCase();
  if (q) rows = rows.filter((r) => `${r.district}, ${r.state}`.toLowerCase().includes(q));
  const [k, dir] = st.sort;
  const key = k === "category" ? "rank" : k;  // category sorts by severity, not alphabetically
  return rows.sort((a, b) => {
    const x = a[key], y = b[key];
    if (x === null || x === "") return 1;
    if (y === null || y === "") return -1;
    return (typeof x === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
  });
}
function downloadCsv(name, cols, lines) {
  const head = cols.map(([, lab]) => t(lab)).concat(["LGD", "date"]);
  const csv = [head].concat(lines).map((l) => l.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = name;
  a.click();
}
function renderGroups() {
  $("#col-groups").innerHTML = `<span>${esc(t("table_columns"))}</span><div>${LAYERS.map((g) =>
    `<button class="filter-chip" data-g="${g}" aria-pressed="${st.groups.has(g)}">${esc(t("group_" + g))}</button>`).join("")}</div>`;
  $("#col-groups").querySelectorAll("button").forEach((b) => b.onclick = () => {
    st.groups.has(b.dataset.g) ? st.groups.delete(b.dataset.g) : st.groups.add(b.dataset.g);
    renderGroups();
    renderTable();
  });
}
function renderTable() {
  const tools = $("#table-tools");
  const qs = ["hidden_drought", "double_drought", "buffered", "fine", "none"];
  const cols = shownCols();
  const rows = filterSort(tableRows());
  const [k, dir] = st.sort;
  tools.innerHTML = `<strong>${esc(t("table_title"))}</strong>
    <button class="filter-chip" data-q="" aria-pressed="${!st.filter}">${esc(t("table_all"))}</button>
    ${qs.map((q) => `<button class="filter-chip" data-q="${q}" aria-pressed="${st.filter === q}">${esc(t(q === "none" ? "q_none" : "q_" + q))}</button>`).join("")}
    <span class="count">${esc(t("table_count", { n: rows.length }))}</span>
    <button class="btn" id="dl">${esc(t("table_download"))}</button>
    <button class="btn" id="dl-all">${esc(t("table_download_all"))}</button>
    <details class="col-help"${$("#table-tools details")?.open ? " open" : ""}><summary>${esc(t("table_help_title"))}</summary><dl>
      ${cols.filter(([, , g]) => GROUP_HELP[g]).map(([, lab, g]) => `<dt>${esc(t(lab))}</dt><dd>${esc(t(lab + "_help"))} <a href="methods.html${GROUP_HELP[g]}">${esc(t("more_in_methods"))}</a></dd>`).join("")}
    </dl></details>`;
  tools.querySelectorAll(".filter-chip").forEach((b) => b.onclick = () => { st.filter = b.dataset.q || null; renderTable(); });
  const cell = (r, [c, , , dec, sg]) => {
    const x = r[c];
    return `<td class="${dec !== undefined ? "num" : ""}">${esc(x === null ? "–" : dec !== undefined ? (sg ? signed(x, dec) : fmt(x, dec)) : x)}</td>`;
  };
  $("#table").innerHTML = `<thead><tr>${cols.map(([c, lab]) => `<th data-k="${c}" title="${esc(t(lab + "_help"))}" aria-sort="${k === c ? (dir > 0 ? "ascending" : "descending") : "none"}">${esc(t(lab))}${k === c ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr data-lgd="${r.lgd}">${cols.map((c) => cell(r, c)).join("")}</tr>`).join("")}</tbody>`;
  $("#table").querySelectorAll("th").forEach((th) => th.onclick = () => {
    st.sort = [th.dataset.k, st.sort[0] === th.dataset.k ? -st.sort[1] : 1];
    renderTable();
  });
  $("#table").querySelectorAll("tbody tr").forEach((tr) => tr.onclick = () => { setView("map"); select(+tr.dataset.lgd); });
  const line = (r, snap) => cols.map(([c]) => r[c] ?? "").concat([r.lgd, snapDate(snap)]);
  $("#dl").onclick = () => downloadCsv(`drought-watch-${st.snapshot === "now" ? "latest" : st.snapshot}.csv`, cols, rows.map((r) => line(r, st.snapshot)));
  // every snapshot plus the latest figures, with the same columns, filter and search as on screen
  $("#dl-all").onclick = async (ev) => {
    const b = ev.currentTarget, snaps = histIndex.snapshots;
    b.disabled = true;
    let done = 0;
    await Promise.all(snaps.map(async (d) => { await loadSnap(d); b.textContent = t("table_loading", { n: ++done, total: snaps.length }); }));
    downloadCsv("drought-watch-all-dates.csv", cols, [...snaps, "now"].flatMap((d) => filterSort(tableRows(d)).map((r) => line(r, d))));
    b.disabled = false;
    b.textContent = t("table_download_all");
  };
}
function setView(view) {
  st.view = view;
  $("#map-view").hidden = view !== "map";
  $("#table-view").hidden = view !== "table";
  $("#nav-map").setAttribute("aria-pressed", view === "map");
  $("#nav-table").setAttribute("aria-pressed", view === "table");
  $("#controls").classList.toggle("for-table", view === "table");
  // the search box filters rows in the table, and names the selected district on the map
  $("#search").value = view === "table" ? st.q : names[st.selected] ? `${names[st.selected].n}, ${names[st.selected].s}` : "";
  st.moved = null;
  syncDates().then(() => { if (view === "table") renderTable(); });
}

// ---------------- controls ----------------
function asofLine() {
  if (st.snapshot === "now") {
    const a = status.as_of;
    $("#asof").textContent = t("asof_line", { rain: a.rain, gw: a.groundwater_cycle, idm: a.idm_week });
  } else {
    const sn = cache.snaps[st.snapshot];
    const fi = sn.fields.indexOf("stress_edition");
    const ed = Object.values(sn.districts).map((r) => r[fi]).find(Boolean);
    $("#asof").textContent = t("snapshot_note", { date: snapLabel(st.snapshot), edition: ed ? "IN-GRES " + ed : t("stress_none_for_date") });
  }
}
async function loadSnap(d) {
  if (d !== "now" && !cache.snaps[d]) cache.snaps[d] = await json(`${DATA}history/s_${d}.json`);
}
async function setSnapshot(d) {
  await loadSnap(d);
  st.snapshot = d;
  asofLine();
  recolor();
  renderPanel();
  if (st.view === "table") renderTable();
}

// Snapshot dates the current layer has data for (stress and the drought index start late).
function layerDates() {
  const from = st.view === "table" ? null : histIndex.layer_from?.[st.layer];  // the table has every date
  return histIndex.snapshots.filter((d) => !from || d >= from);
}
function fillDates() {
  const date = $("#date");
  date.innerHTML = `<option value="now">${esc(t("date_now"))}</option>` +
    layerDates().reverse().map((d) => `<option value="${d}">${esc(snapLabel(d))} · ${histIndex.classified[d]} districts</option>`).join("");
  date.value = st.snapshot;
}
// Refill the date list for the current layer/view. If the chosen date is older than the
// layer's data, move to the layer's first date and say so on the map.
async function syncDates() {
  const dates = layerDates();
  if (st.snapshot !== "now" && !dates.includes(st.snapshot)) {
    st.moved = dates[0] || null;
    st.snapshot = dates[0] || "now";
    fillDates();
    await setSnapshot(st.snapshot);
  } else {
    fillDates();
    recolor();
    renderPanel();
  }
}
const CTL_HELP = [["layer_quadrant", "#categories"], ["layer_rain", "#rain"], ["layer_gw", "#groundwater"],
  ["layer_stress", "#stress"], ["layer_idm", "#drought-index"], ["ctl_date", "#history"]];

function initControls() {
  const layer = $("#layer");
  layer.innerHTML = LAYERS.map((l) => `<option value="${l}">${esc(t("layer_" + l))}</option>`).join("");
  layer.onchange = async () => {
    st.layer = layer.value;
    st.moved = null;
    await syncDates();
  };
  const date = $("#date");
  fillDates();
  date.onchange = () => { st.moved = null; setSnapshot(date.value); };
  $("#ctl-help").innerHTML = `<summary>${esc(t("ctl_help_title"))}</summary><dl>
    ${CTL_HELP.map(([k, a]) => `<dt>${esc(t(k))}</dt><dd>${esc(t(k + "_help"))} <a href="methods.html${a}">${esc(t("more_in_methods"))}</a></dd>`).join("")}
  </dl>`;
  const dl = $("#district-list");
  const list = geo.features.filter((f) => f.properties.lgd).map((f) => `${f.properties.n}, ${f.properties.s}`);
  dl.innerHTML = list.map((x) => `<option value="${esc(x)}">`).join("");
  $("#search").setAttribute("placeholder", t("search_placeholder"));
  $("#search").oninput = (e) => { if (st.view === "table") { st.q = e.target.value; renderTable(); } };
  renderGroups();
  $("#search").onchange = (e) => {
    if (st.view === "table") return;
    const f = geo.features.find((g) => `${g.properties.n}, ${g.properties.s}` === e.target.value);
    if (f) { setView("map"); select(f.properties.lgd); }
  };
  $("#nav-map").onclick = () => setView("map");
  $("#nav-table").onclick = () => setView("table");
}

// ---------------- boot ----------------
async function main() {
  S = await json("i18n/en.json");
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  [geo, status, histIndex] = await Promise.all([json(DATA + "districts.geojson"), json(DATA + "status.json"), json(DATA + "history/index.json")]);
  for (const f of geo.features) if (f.properties.lgd) names[f.properties.lgd] = { n: f.properties.n, s: f.properties.s };
  initControls();
  asofLine();
  drawMap();
  if (location.hash === "#table") setView("table");
  const want = new URLSearchParams(location.search).get("d");
  if (want && names[want]) select(+want); else renderPanel();
}
main().catch((e) => { document.body.insertAdjacentHTML("beforeend", `<p style="padding:16px;color:#d03b3b">Failed to load: ${esc(e.message)}</p>`); });
