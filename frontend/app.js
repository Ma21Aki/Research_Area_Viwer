// outputs/summary.json(バックエンドの出力)だけを読んで描画する。バックエンドのコードには依存しない。
const DATA_URL = "data/summary.json";
const COLORS = ["--s1", "--s2", "--s3", "--s4", "--s5"];
const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const pct = (v, d = 2) => (v == null ? "–" : (v * 100).toFixed(d) + "%");

function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent.appendChild(e);
  return e;
}

function draw(doc) {
  const svg = $("chart");
  svg.replaceChildren();
  // 実表示幅に合わせて描くと、スマホでも文字が縮まず読める
  const W = Math.max(300, Math.round(svg.getBoundingClientRect().width)), H = Math.round(W * 0.68);
  const m = { l: 44, r: 12, t: 10, b: 24 };
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const years = doc.fields[0].years;
  const x0 = years[0], x1 = years[years.length - 1];
  const ymax = Math.max(...doc.fields.flatMap((f) => f.ratio.filter((v) => v != null))) * 1.08 || 1;
  const X = (y) => m.l + ((y - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const Y = (v) => H - m.b - (v / ymax) * (H - m.t - m.b);
  for (let i = 0; i <= 4; i++) {
    const v = (ymax * i) / 4;
    el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: css("--grid"), "stroke-width": 1 }, svg);
    const t = el("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end", "font-size": 11, fill: css("--ink2") }, svg);
    t.textContent = pct(v, 1);
  }
  for (let y = x0 - (x0 % 5) + 5; y <= x1; y += 5) {
    const t = el("text", { x: X(y), y: H - 6, "text-anchor": "middle", "font-size": 11, fill: css("--ink2") }, svg);
    t.textContent = y;
  }
  const path = (f, key) => {
    let d = "", pen = false;
    f[key].forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${X(f.years[i]).toFixed(1)},${Y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  doc.fields.forEach((f, i) => {
    const c = css(COLORS[i % COLORS.length]);
    el("path", { d: path(f, "ratio"), fill: "none", stroke: c, "stroke-width": 1, opacity: 0.45 }, svg);
    el("path", { d: path(f, "ratio_ma3"), fill: "none", stroke: c, "stroke-width": 2.2, "stroke-linecap": "round" }, svg);
  });
  const cross = el("line", { y1: m.t, y2: H - m.b, stroke: css("--ink2"), "stroke-width": 1, visibility: "hidden" }, svg);
  const tip = $("tip");
  const move = (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    const y = Math.min(x1, Math.max(x0, Math.round(x0 + ((px - m.l) / (W - m.l - m.r)) * (x1 - x0))));
    cross.setAttribute("x1", X(y)); cross.setAttribute("x2", X(y)); cross.setAttribute("visibility", "visible");
    const i = years.indexOf(y);
    tip.innerHTML = `<b>${y}</b><br>` + doc.fields.map((f) => `${f.display_name}: ${pct(f.ratio[i])}`).join("<br>");
    tip.style.display = "block";
    const wrap = svg.parentElement.getBoundingClientRect();
    const left = ev.clientX - wrap.left + 12;
    tip.style.left = Math.min(left, wrap.width - tip.offsetWidth - 4) + "px";
    tip.style.top = "12px";
  };
  svg.onpointermove = move; svg.onpointerdown = move;
  svg.onpointerleave = () => { cross.setAttribute("visibility", "hidden"); tip.style.display = "none"; };
  $("legend").innerHTML = doc.fields
    .map((f, i) => `<span><i style="background:var(${COLORS[i % COLORS.length]})"></i>${f.display_name}</span>`)
    .join("");
}

function fill(doc) {
  const last = (a) => a[a.length - 1];
  const rows = doc.fields.map((f, i) => `<tr>
    <td><i style="display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:var(${COLORS[i % COLORS.length]})"></i>${f.display_name}</td>
    <td>${last(f.count)}</td><td>${pct(last(f.ratio))}</td><td>${pct(last(f.ratio_ma3))}</td>
    <td>${last(f.ratio_yoy) == null ? "–" : (last(f.ratio_yoy) * 100).toFixed(1) + "%"}</td></tr>`).join("");
  $("table").innerHTML = `<tr><th>分野(${last(doc.fields[0].years)}年)</th><th>件数</th><th>比率</th><th>3年平均</th><th>前年比</th></tr>${rows}`;
  $("meta").textContent = `分母: ${doc.subfield.name} / 更新: ${doc.generated_at.replace("T", " ").replace("+00:00", " UTC")}`;
}

fetch(DATA_URL, { cache: "no-cache" })
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((doc) => {
    fill(doc);
    draw(doc);
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => draw(doc));
    let w = $("chart").clientWidth;
    addEventListener("resize", () => { if ($("chart").clientWidth !== w) { w = $("chart").clientWidth; draw(doc); } });
  })
  .catch((e) => {
    $("meta").textContent = "";
    const box = $("error"); box.hidden = false;
    box.textContent = `分析結果(${DATA_URL})を読み込めませんでした。GitHub Actions の分析ワークフローを実行してください。(${e.message})`;
  });
