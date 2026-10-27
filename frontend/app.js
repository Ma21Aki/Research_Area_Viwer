// バックエンドの出力(dashboard.json)だけを読んで描画する。バックエンドのコードには依存しない。
// 出現率・移動平均は画面側で計算する(分母・指標を、再検索なしで切り替えられる)。
// PC版(ローカルサーバー)では /api/ が使えるので、トピックの追加・削除・語句の編集もできる。
// 公開サイト(GitHub Pages)では閲覧のみ。
const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const METRICS = [
  { key: "ratio", name: "出現率", scoped: true, desc: "タイトルに語句を含む論文数 ÷ 分母の論文数" },
  { key: "count", name: "論文数", scoped: true, desc: "タイトルに語句を含む論文数(出版年別)" },
  { key: "cites_received", name: "被引用数", desc: "その年に、一致した論文全体が受けた被引用数(引用された年別)" },
  { key: "mean_cites", name: "被引用/論文", desc: "出版年ごとの、1論文あたりの累計被引用数(新しい論文ほど不利)" },
  { key: "fwci_mean", name: "FWCI", desc: "分野・年・種別で正規化した被引用(1.0 が平均)の平均" },
  { key: "top10_share", name: "上位10%率", desc: "被引用が同分野・同年で上位10%に入る論文の割合", pct: true },
];
const state = { metric: "ratio", scope: "all", smooth: false, hidden: new Set() };
const ui = { editable: false, defs: [], open: new Set(), busy: false };
let doc = null;

try {
  Object.assign(state, JSON.parse(localStorage.getItem("view") || "{}"));
  state.hidden = new Set(JSON.parse(localStorage.getItem("hidden") || "[]"));
} catch (e) {}
const save = () => {
  try {
    localStorage.setItem("view", JSON.stringify({ metric: state.metric, scope: state.scope, smooth: state.smooth }));
    localStorage.setItem("hidden", JSON.stringify([...state.hidden]));
  } catch (e) {}
};

function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent.appendChild(e);
  return e;
}
// 色はトピックに固定(topics.json の color)。追加・削除で他のトピックの色は変わらない
const cvar = (t) => `var(--s${(t.color % 8) + 1})`;
const color = (t) => css(`--s${(t.color % 8) + 1}`);

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

// ---- グラフ ----
function draw() {
  const svg = $("chart"); svg.replaceChildren();
  const W = Math.max(300, Math.round(svg.getBoundingClientRect().width)), H = Math.round(W * (W > 700 ? 0.5 : 0.7));
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.style.aspectRatio = `${W} / ${H}`;
  const m = { l: 48, r: 12, t: 10, b: 24 }, years = doc.years, x0 = years[0], x1 = years[years.length - 1];
  const data = doc.topics.filter((t) => !state.hidden.has(t.label)).map((t) => ({ t, s: series(t) }));
  const vals = data.flatMap((d) => d.s.filter((v) => v != null));
  const ymax = (vals.length ? Math.max(...vals) : 1) * 1.08 || 1;
  const X = (y) => m.l + ((y - x0) / (x1 - x0 || 1)) * (W - m.l - m.r), Y = (v) => H - m.b - (v / ymax) * (H - m.t - m.b);
  for (let k = 0; k <= 4; k++) {
    const v = (ymax * k) / 4;
    el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: css("--grid"), "stroke-width": 1 }, svg);
    el("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end", "font-size": 11, fill: css("--ink2") }, svg).textContent = fmtTick(v, ymax);
  }
  const step = x1 - x0 <= 12 ? 1 : 5; // 年の範囲が短いときは毎年に目盛り
  for (let y = step === 1 ? x0 : x0 - (x0 % 5) + 5; y <= x1; y += step)
    el("text", { x: X(y), y: H - 6, "text-anchor": y === x1 ? "end" : "middle", "font-size": 11, fill: css("--ink2") }, svg).textContent = y;
  for (const d of data) {
    let p = "", pen = false;
    d.s.forEach((v, k) => { if (v == null) { pen = false; return; } p += `${pen ? "L" : "M"}${X(years[k]).toFixed(1)},${Y(v).toFixed(1)}`; pen = true; });
    el("path", { d: p, fill: "none", stroke: color(d.t), "stroke-width": 2.2, "stroke-linecap": "round", "stroke-linejoin": "round" }, svg);
    const k = years.indexOf(doc.partial_year); // 今年は途中経過: 白抜きの点で示す
    if (k >= 0 && d.s[k] != null) el("circle", { cx: X(years[k]), cy: Y(d.s[k]), r: 4, fill: css("--surface"), stroke: color(d.t), "stroke-width": 2 }, svg);
  }
  if (!vals.length) el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", "font-size": 13, fill: css("--ink2") }, svg).textContent = "表示できるデータがありません";
  const cross = el("line", { y1: m.t, y2: H - m.b, stroke: css("--ink2"), "stroke-width": 1, visibility: "hidden" }, svg);
  const tip = $("tip");
  const move = (ev) => {
    const r = svg.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
    const y = Math.min(x1, Math.max(x0, Math.round(x0 + ((px - m.l) / (W - m.l - m.r)) * (x1 - x0)))), k = years.indexOf(y);
    cross.setAttribute("x1", X(y)); cross.setAttribute("x2", X(y)); cross.setAttribute("visibility", "visible");
    tip.innerHTML = `<b>${y}${y === doc.partial_year ? "(途中)" : ""}</b><br>` +
      data.map((d) => `<i style="background:${color(d.t)}"></i>${esc(d.t.display_name)}: ${fmt(d.s[k])}`).join("<br>");
    tip.style.display = "block";
    const w = svg.parentElement.getBoundingClientRect();
    tip.style.left = Math.max(4, Math.min(ev.clientX - w.left + 12, w.width - tip.offsetWidth - 4)) + "px"; tip.style.top = "12px";
  };
  svg.onpointermove = move; svg.onpointerdown = move;
  svg.onpointerleave = () => { cross.setAttribute("visibility", "hidden"); tip.style.display = "none"; };
}

function table() {
  const years = doc.years, p = doc.partial_year, lastIdx = years.length - 1 - (p === years[years.length - 1] ? 1 : 0);
  const sw = (t) => `<i style="display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:${cvar(t)}"></i>`;
  const rows = doc.topics.map((t) => {
    const s = series(t), a = s[lastIdx], b = s[lastIdx - 1], cur = p ? s[years.indexOf(p)] : null;
    const yoy = a == null || b == null || b === 0 ? "–" : ((a / b - 1) * 100).toFixed(1) + "%";
    return `<tr><td>${sw(t)}${esc(t.display_name)}</td><td>${fmt(a)}</td><td>${yoy}</td><td>${p ? fmt(cur) : "–"}</td></tr>`;
  }).join("");
  $("table").innerHTML = `<tr><th>トピック</th><th>${years[lastIdx]}年</th><th>前年比</th><th>${p ? p + "年(途中)" : ""}</th></tr>${rows}`;
}

// ---- トピック欄 ----
// 表示は見出し語句だけ。「詳細設定」で言い換え(OR検索)と除外語句を下に展開する
function defOf(label) { return ui.defs.find((d) => d.id === label); }

function tagList(items, kind, label) {
  const rm = (i) => (ui.editable ? `<button type="button" data-act="rm" data-kind="${kind}" data-id="${esc(label)}" data-i="${i}" aria-label="削除" ${ui.busy ? "disabled" : ""}>×</button>` : "");
  if (!items.length) return `<span class="muted">なし</span>`;
  return items.map((x, i) => `<span class="tag">${esc(x.phrase)} <span class="n">${x.note}</span>${rm(i)}</span>`).join("");
}
function addForm(kind, label, ph) {
  if (!ui.editable) return "";
  return `<form class="add" data-kind="${kind}" data-id="${esc(label)}"><input name="w" maxlength="120" placeholder="${ph}" aria-label="${ph}" ${ui.busy ? "disabled" : ""}><button class="opt small" ${ui.busy ? "disabled" : ""}>追加</button></form>`;
}

function topicsPanel() {
  $("topicCard").hidden = false;
  $("newTopic").hidden = !ui.editable;
  for (const x of $("newTopic").elements) x.disabled = ui.busy;
  $("topicNote").textContent = ui.editable
    ? "語句はタイトルに対するフレーズ検索。除外語句は単語単位で照合し、複数形(s/es)も含む。新しい語句の取得には数十秒かかることがある。"
    : "トピックの編集は PC版(ローカルで起動したダッシュボード)で行う。";
  $("topics").innerHTML = doc.topics.map((t) => {
    const open = ui.open.has(t.label);
    const syn = t.phrases.slice(1).map((p) => ({ phrase: p.phrase, note: p.merged_into ? "(同一視)" : `${p.count.toLocaleString()}件` }));
    const exc = (t.excludes || []).map((e) => ({ phrase: e.phrase, note: `${e.count.toLocaleString()}件除外` }));
    const head = t.phrases[0];
    return `<div class="topic">
      <div class="topic-row">
        <button class="chip" data-act="toggle" data-id="${esc(t.label)}" aria-pressed="${!state.hidden.has(t.label)}" style="--c:${cvar(t)}"><i></i>${esc(t.display_name)}</button>
        <button class="opt small" data-act="detail" data-id="${esc(t.label)}" aria-expanded="${open}">詳細設定 ${open ? "▴" : "▾"}</button>
      </div>
      <div class="detail" ${open ? "" : "hidden"}>
        <div class="muted">見出し語句 ${head ? head.count.toLocaleString() + "件" : ""}${t.excluded ? ` / 除外後 ${(t.series.count_all.reduce((a, b) => a + (b || 0), 0)).toLocaleString()}件(${t.excluded.toLocaleString()}件除外)` : ""}</div>
        <h3>言い換え(OR で並列検索)</h3><div class="tags">${tagList(syn, "synonyms", t.label)}</div>
        ${addForm("synonyms", t.label, "言い換えを追加(例: state-space models)")}
        <h3>除外語句(タイトルに含む論文を除く)</h3><div class="tags">${tagList(exc, "excludes", t.label)}</div>
        ${addForm("excludes", t.label, "除外語句を追加(例: mamba)")}
        ${ui.editable ? `<p><button type="button" class="opt small danger" data-act="delete" data-id="${esc(t.label)}" ${ui.busy || doc.topics.length <= 1 ? "disabled" : ""}>このトピックを削除</button></p>` : ""}
      </div></div>`;
  }).join("");
}

function setStatus(msg, kind) {
  const box = $("status");
  if (!msg) { box.hidden = true; return; }
  box.hidden = false;
  box.className = "card" + (kind === "error" ? " err" : "");
  box.innerHTML = msg;
}

async function api(method, path, body) {
  const r = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined, cache: "no-store" });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

// 編集は「全トピックの定義」を送り、サーバーが取得・集計に成功したら保存する
async function submit(defs) {
  try {
    ui.busy = true; topicsPanel();
    await api("PUT", "api/topics", { topics: defs });
    await follow();
  } catch (e) {
    ui.busy = false; topicsPanel();
    setStatus(`保存できませんでした: ${esc(e.message)}`, "error");
  }
}

// 取得・集計の進み具合を表示し、終わったら最新のデータを読み直す
async function follow() {
  for (;;) {
    const st = await api("GET", "api/state");
    const j = st.job;
    if (j.state === "running") {
      ui.busy = true;
      const bar = j.total ? `<progress max="${j.total}" value="${Math.min(j.done, j.total)}"></progress>` : "";
      setStatus(`${esc(j.message)}… ${j.total ? `${Math.min(j.done, j.total)} / ${j.total} リクエスト` : ""}${bar}`);
      await new Promise((ok) => setTimeout(ok, 700));
      continue;
    }
    ui.busy = false;
    if (j.state === "error") setStatus(`取得に失敗しました(変更は保存していません): ${esc(j.message)}`, "error");
    else setStatus("");
    break;
  }
  ui.defs = (await api("GET", "api/topics")).topics;
  try { doc = await api("GET", "api/dashboard"); } catch (e) { /* 初回の集計に失敗した場合は表示なし */ }
  if (doc) { init(); }
}

function edit(label, fn) {
  const defs = structuredClone(ui.defs);
  const d = defs.find((x) => x.id === label);
  if (!d) return;
  fn(d, defs);
  submit(defs);
}

function onTopicsClick(e) {
  const b = e.target.closest("button[data-act]");
  if (!b || b.disabled) return;
  const id = b.dataset.id;
  if (b.dataset.act === "toggle") { state.hidden.has(id) ? state.hidden.delete(id) : state.hidden.add(id); render(); return; }
  if (b.dataset.act === "detail") { ui.open.has(id) ? ui.open.delete(id) : ui.open.add(id); topicsPanel(); return; }
  if (b.dataset.act === "rm") edit(id, (d) => d[b.dataset.kind].splice(Number(b.dataset.i), 1));
  if (b.dataset.act === "delete" && confirm(`「${defOf(id).headword}」を削除しますか?`)) {
    const defs = ui.defs.filter((x) => x.id !== id);
    ui.open.delete(id); submit(defs);
  }
}
function onTopicsSubmit(e) {
  const f = e.target.closest("form.add");
  if (!f) return;
  e.preventDefault();
  const w = f.elements.w.value.trim();
  if (!w || ui.busy) return;
  if (f.id === "newTopic") {
    f.elements.w.value = "";
    submit([...structuredClone(ui.defs), { headword: w, synonyms: [], excludes: [] }]);
    return;
  }
  edit(f.dataset.id, (d) => d[f.dataset.kind].push(w));
}

// ---- 全体 ----
function render() {
  const def = METRICS.find((x) => x.key === state.metric);
  $("scopeBox").hidden = !def.scoped;
  $("chartNote").textContent = def.desc + (doc.partial_year ? `。白抜きの点は ${doc.partial_year} 年(途中経過)。` : "") + (state.smooth ? " 3年平均で表示中。" : "");
  const sc = doc.denominators[state.scope].name;
  $("tableNote").textContent = def.scoped ? `集計範囲: ${sc}` + (doc.work_type ? `(論文種別: ${doc.work_type})` : "") : (doc.work_type ? `論文種別: ${doc.work_type}` : "");
  for (const b of document.querySelectorAll("#metrics button")) b.setAttribute("aria-pressed", b.dataset.k === state.metric);
  for (const b of document.querySelectorAll("#scopes button")) b.setAttribute("aria-pressed", b.dataset.k === state.scope);
  for (const b of document.querySelectorAll("#smooth button")) b.setAttribute("aria-pressed", (b.dataset.k === "ma") === state.smooth);
  topicsPanel(); draw(); table(); save();
}

let wired = false;
function init() {
  $("metrics").innerHTML = METRICS.map((m) => `<button class="opt" data-k="${m.key}" ${hasData(m.key) ? "" : "disabled title='データなし'"}>${m.name}</button>`).join("");
  $("scopes").innerHTML = Object.entries(doc.denominators).map(([k, v]) => `<button class="opt" data-k="${k}">${esc(v.name)}</button>`).join("");
  $("smooth").innerHTML = `<button class="opt" data-k="raw">年次</button><button class="opt" data-k="ma">3年平均</button>`;
  if (!METRICS.some((m) => m.key === state.metric && hasData(m.key))) state.metric = "ratio";
  if (!doc.denominators[state.scope]) state.scope = doc.default_denominator;
  $("controls").hidden = false;
  $("meta").textContent = `更新: ${doc.generated_at.replace("T", " ").replace("+00:00", " UTC")}` + (ui.editable ? " ・PC版(編集可)" : "");
  render();
  if (wired) return;
  wired = true;
  $("metrics").onclick = (e) => { const b = e.target.closest("button:not(:disabled)"); if (b) { state.metric = b.dataset.k; render(); } };
  $("scopes").onclick = (e) => { const b = e.target.closest("button"); if (b) { state.scope = b.dataset.k; render(); } };
  $("smooth").onclick = (e) => { const b = e.target.closest("button"); if (b) { state.smooth = b.dataset.k === "ma"; render(); } };
  $("topicCard").addEventListener("click", onTopicsClick);
  $("topicCard").addEventListener("submit", onTopicsSubmit);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
  let w = $("chart").clientWidth;
  addEventListener("resize", () => { if ($("chart").clientWidth !== w) { w = $("chart").clientWidth; draw(); } });
}

function fail(msg) {
  $("meta").textContent = "";
  const box = $("error"); box.hidden = false;
  box.textContent = msg;
}

// PC版(ローカルサーバー)なら /api/ を使い、公開サイトなら data/dashboard.json を読む
(async () => {
  try {
    const st = await api("GET", "api/state");
    ui.editable = !!st.editable;
  } catch (e) { ui.editable = false; }
  if (ui.editable) {
    await follow().catch((e) => fail(`ダッシュボードのサーバーに接続できませんでした。(${e.message})`));
    if (!doc && !$("status").classList.contains("err")) fail("集計結果がありません。");
    return;
  }
  fetch("data/dashboard.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => { doc = d; doc.topics.forEach((t, i) => { if (t.color == null) t.color = i; }); init(); })
    .catch((e) => fail(`分析結果を読み込めませんでした。GitHub Actions の分析ワークフロー(run)を実行してください。(${e.message})`));
})();
