// outputs/dashboard.json(バックエンドの出力)だけを読んで描画する。バックエンドのコードには依存しない。
// 出現率・移動平均は画面側で計算する(分母・指標を、再検索なしで切り替えられる)。
const DATA_URL = "data/dashboard.json";
const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const METRICS = [
  { key: "ratio", name: "出現率", scoped: true, desc: "タイトルに語句を含む論文数 ÷ 分母の論文数" },
  { key: "count", name: "論文数", scoped: true, desc: "タイトルに語句を含む論文数(出版年別)" },
  { key: "cites_received", name: "被引用数", desc: "その年に、一致した論文全体が受けた被引用数(引用された年別)" },
  { key: "mean_cites", name: "被引用/論文", desc: "出版年ごとの、1論文あたりの累計被引用数(新しい論文ほど不利)" },
  { key: "fwci_mean", name: "FWCI", desc: "分野・年・種別で正規化した被引用(1.0 が平均)の平均" },
  { key: "top10_share", name: "上位10%率", desc: "被引用が同分野・同年で上位10%に入る論文の割合", pct: true },
];
const state = { metric: "ratio", scope: "all", smooth: false, hidden: new Set() };
let doc = null;

try { Object.assign(state, JSON.parse(localStorage.getItem("view") || "{}"), { hidden: new Set(JSON.parse(localStorage.getItem("hidden") || "[]")) }); } catch (e) {}
const save = () => { try { localStorage.setItem("view", JSON.stringify({ metric: state.metric, scope: state.scope, smooth: state.smooth })); localStorage.setItem("hidden", JSON.stringify([...state.hidden])); } catch (e) {} };

function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent.appendChild(e);
  return e;
}
const color = (i) => css(`--s${(i % 8) + 1}`);

// ---- 系列の計算 ----
function rawSeries(t) {
  const m = state.metric;
  if (m === "ratio") {
    const d = doc.denominators[state.scope].series;
    return t.series[`count_${state.scope}`].map((c, i) => (c == null || !d[i] ? null : c / d[i]));
  }
  if (m === "count") return t.series[`count_${state.scope}`];
  return t.series[m];
}
function ma3(a) { // 当該年を含む直近3年。3年揃わない年は null
  return a.map((_, i) => (i < 2 || a.slice(i - 2, i + 1).some((v) => v == null) ? null : (a[i] + a[i - 1] + a[i - 2]) / 3));
}
const series = (t) => (state.smooth ? ma3(rawSeries(t)) : rawSeries(t));
const hasData = (key) => doc.topics.some((t) => (key === "ratio" || key === "count" ? t.series.count_all : t.series[key]).some((v) => v != null));

function fmt(v, big) {
  if (v == null) return "–";
  const m = state.metric, def = METRICS.find((x) => x.key === m);
  if (m === "ratio" || def.pct) { const p = v * 100; return p.toFixed(p >= 10 ? 1 : p >= 1 ? 2 : 3) + "%"; }
  if (m === "count" || m === "cites_received") return big && v >= 10000 ? (v / 1000).toFixed(0) + "k" : Math.round(v).toLocaleString();
  return v.toFixed(m === "fwci_mean" ? 2 : 1);
}

// 縦軸の目盛りは桁数を揃える(最大値に応じて小数桁を決める)
function fmtTick(v, ymax) {
  const def = METRICS.find((x) => x.key === state.metric);
  if (state.metric === "ratio" || def.pct) {
    const pm = ymax * 100;
    return (v * 100).toFixed(pm >= 10 ? 0 : pm >= 2 ? 1 : pm >= 0.2 ? 2 : 3) + "%";
  }
  if (state.metric === "fwci_mean") return v.toFixed(1);
  if (state.metric === "mean_cites") return v.toFixed(ymax >= 10 ? 0 : 1);
  return fmt(v, true);
}

// ---- 描画 ----
function draw() {
  const svg = $("chart"); svg.replaceChildren();
  const W = Math.max(300, Math.round(svg.getBoundingClientRect().width)), H = Math.round(W * 0.7);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.style.aspectRatio = `${W} / ${H}`;
  const m = { l: 48, r: 12, t: 10, b: 24 }, years = doc.years, x0 = years[0], x1 = years[years.length - 1];
  const vis = doc.topics.map((t, i) => ({ t, i })).filter(({ t }) => !state.hidden.has(t.label));
  const data = vis.map(({ t, i }) => ({ t, i, s: series(t) }));
  const vals = data.flatMap((d) => d.s.filter((v) => v != null));
  const ymax = (vals.length ? Math.max(...vals) : 1) * 1.08 || 1;
  const X = (y) => m.l + ((y - x0) / (x1 - x0 || 1)) * (W - m.l - m.r), Y = (v) => H - m.b - (v / ymax) * (H - m.t - m.b);
  for (let k = 0; k <= 4; k++) {
    const v = (ymax * k) / 4;
    el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: css("--grid"), "stroke-width": 1 }, svg);
    el("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end", "font-size": 11, fill: css("--ink2") }, svg).textContent = fmtTick(v, ymax);
  }
  for (let y = x0 - (x0 % 5) + 5; y <= x1; y += 5)
    el("text", { x: X(y), y: H - 6, "text-anchor": "middle", "font-size": 11, fill: css("--ink2") }, svg).textContent = y;
  for (const d of data) {
    let p = "", pen = false;
    d.s.forEach((v, k) => { if (v == null) { pen = false; return; } p += `${pen ? "L" : "M"}${X(years[k]).toFixed(1)},${Y(v).toFixed(1)}`; pen = true; });
    el("path", { d: p, fill: "none", stroke: color(d.i), "stroke-width": 2.2, "stroke-linecap": "round", "stroke-linejoin": "round" }, svg);
    const k = years.indexOf(doc.partial_year); // 今年は途中経過: 白抜きの点で示す
    if (k >= 0 && d.s[k] != null) el("circle", { cx: X(years[k]), cy: Y(d.s[k]), r: 4, fill: css("--surface"), stroke: color(d.i), "stroke-width": 2 }, svg);
  }
  if (!vals.length) el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", "font-size": 13, fill: css("--ink2") }, svg).textContent = "表示できるデータがありません";
  const cross = el("line", { y1: m.t, y2: H - m.b, stroke: css("--ink2"), "stroke-width": 1, visibility: "hidden" }, svg);
  const tip = $("tip");
  const move = (ev) => {
    const r = svg.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
    const y = Math.min(x1, Math.max(x0, Math.round(x0 + ((px - m.l) / (W - m.l - m.r)) * (x1 - x0)))), k = years.indexOf(y);
    cross.setAttribute("x1", X(y)); cross.setAttribute("x2", X(y)); cross.setAttribute("visibility", "visible");
    tip.innerHTML = `<b>${y}${y === doc.partial_year ? "(途中)" : ""}</b><br>` + data.map((d) => `<i style="background:${color(d.i)}"></i>${d.t.display_name}: ${fmt(d.s[k])}`).join("<br>");
    tip.style.display = "block";
    const w = svg.parentElement.getBoundingClientRect();
    tip.style.left = Math.max(4, Math.min(ev.clientX - w.left + 12, w.width - tip.offsetWidth - 4)) + "px"; tip.style.top = "12px";
  };
  svg.onpointermove = move; svg.onpointerdown = move;
  svg.onpointerleave = () => { cross.setAttribute("visibility", "hidden"); tip.style.display = "none"; };
}

function table() {
  const years = doc.years, p = doc.partial_year, lastIdx = years.length - 1 - (p === years[years.length - 1] ? 1 : 0);
  const rows = doc.topics.map((t, i) => {
    const s = series(t), a = s[lastIdx], b = s[lastIdx - 1], cur = p ? s[years.indexOf(p)] : null;
    const yoy = a == null || b == null || b === 0 ? "–" : ((a / b - 1) * 100).toFixed(1) + "%";
    return `<tr><td><i style="display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:${color(i)}"></i>${t.display_name}</td><td>${fmt(a)}</td><td>${yoy}</td><td>${p ? fmt(cur) : "–"}</td></tr>`;
  }).join("");
  $("table").innerHTML = `<tr><th>トピック</th><th>${years[lastIdx]}年</th><th>前年比</th><th>${p ? p + "年(途中)" : ""}</th></tr>${rows}`;
}

function phrases() {
  $("phrases").innerHTML = doc.topics.map((t, i) => `<details><summary><i style="width:10px;height:10px;border-radius:2px;background:${color(i)};display:inline-block"></i><b>${t.display_name}</b></summary>
    <div class="phr">${t.phrases.map((p) => `<span>${p.phrase}${p.merged_into ? `(「${p.merged_into}」と同一視)` : ` ${p.count.toLocaleString()}件`}</span>`).join("")}</div></details>`).join("");
}

function render() {
  const def = METRICS.find((x) => x.key === state.metric);
  $("scopeBox").hidden = !def.scoped;
  $("chartNote").textContent = def.desc + (doc.partial_year ? `。白抜きの点は ${doc.partial_year} 年(途中経過)。` : "") + (state.smooth ? " 3年平均で表示中。" : "");
  const sc = doc.denominators[state.scope].name;
  $("tableNote").textContent = def.scoped ? `集計範囲: ${sc}` + (doc.work_type ? `(論文種別: ${doc.work_type})` : "") : (doc.work_type ? `論文種別: ${doc.work_type}` : "");
  for (const b of document.querySelectorAll("#metrics button")) b.setAttribute("aria-pressed", b.dataset.k === state.metric);
  for (const b of document.querySelectorAll("#scopes button")) b.setAttribute("aria-pressed", b.dataset.k === state.scope);
  for (const b of document.querySelectorAll("#smooth button")) b.setAttribute("aria-pressed", (b.dataset.k === "ma") === state.smooth);
  for (const b of document.querySelectorAll("#topics button")) b.setAttribute("aria-pressed", !state.hidden.has(b.dataset.k));
  draw(); table(); save();
}

function init() {
  $("metrics").innerHTML = METRICS.map((m) => `<button class="opt" data-k="${m.key}" ${hasData(m.key) ? "" : "disabled title='データなし'"}>${m.name}</button>`).join("");
  $("scopes").innerHTML = Object.entries(doc.denominators).map(([k, v]) => `<button class="opt" data-k="${k}">${v.name}</button>`).join("");
  $("smooth").innerHTML = `<button class="opt" data-k="raw">年次</button><button class="opt" data-k="ma">3年平均</button>`;
  $("topics").innerHTML = doc.topics.map((t, i) => `<button class="chip" data-k="${t.label}" style="--c:${"var(--s" + ((i % 8) + 1) + ")"}"><i></i>${t.display_name}</button>`).join("");
  if (!METRICS.some((m) => m.key === state.metric && hasData(m.key))) state.metric = "ratio";
  if (!doc.denominators[state.scope]) state.scope = doc.default_denominator;
  $("metrics").onclick = (e) => { const b = e.target.closest("button:not(:disabled)"); if (b) { state.metric = b.dataset.k; render(); } };
  $("scopes").onclick = (e) => { const b = e.target.closest("button"); if (b) { state.scope = b.dataset.k; render(); } };
  $("smooth").onclick = (e) => { const b = e.target.closest("button"); if (b) { state.smooth = b.dataset.k === "ma"; render(); } };
  $("topics").onclick = (e) => { const b = e.target.closest("button"); if (b) { state.hidden.has(b.dataset.k) ? state.hidden.delete(b.dataset.k) : state.hidden.add(b.dataset.k); render(); } };
  $("controls").hidden = false;
  $("meta").textContent = `更新: ${doc.generated_at.replace("T", " ").replace("+00:00", " UTC")}`;
  phrases(); render();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { phrases(); render(); });
  let w = $("chart").clientWidth;
  addEventListener("resize", () => { if ($("chart").clientWidth !== w) { w = $("chart").clientWidth; draw(); } });
}

fetch(DATA_URL, { cache: "no-cache" })
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((d) => { doc = d; init(); })
  .catch((e) => {
    $("meta").textContent = "";
    const box = $("error"); box.hidden = false;
    box.textContent = `分析結果(${DATA_URL})を読み込めませんでした。GitHub Actions の分析ワークフロー(run)を実行してください。(${e.message})`;
  });
