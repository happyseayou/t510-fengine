"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const COLORS = [
  "#1769aa", "#d76b24", "#008c95", "#7651a6",
  "#397b58", "#b74842", "#8a6d1d", "#5b6fb0",
  "#a34f8b", "#287c71", "#a85b2a", "#4f718c",
  "#6e8240", "#9a4e55", "#5367a3", "#7a5a3d",
];
const PAGE_SIZE = 4;
const GPU_PLOT_BUDGET = 1;
const GPU_TRACE_SLOTS = 64;
const GPU_DEFAULT_HEIGHT = 520;
const gpuPlots = new Map();
let gpuSurface = null;
let gpuOwner = null;
let gpuInitialized = false;
let gpuFatalError = null;
let gpuDesiredTarget = null;
let gpuQueue = Promise.resolve();
let gpuManualTarget = null;
let gpuObserverFrame = 0;
let GPU_DIAGNOSTIC;
let META;
let state = {mode: "single", page: 0};
const renderGeneration = {time: 0, fengine: 0, allan: 0};
const refreshTimers = new Map();
window.stage35RenderCounters = {time: 0, fengine: 0, allan: 0};

function requireWebGL() {
  GPU_DIAGNOSTIC = {
    webgl1Api: typeof window.WebGLRenderingContext !== "undefined",
    webgl2Api: typeof window.WebGL2RenderingContext !== "undefined",
    plotlyVersion: window.Plotly?.version || "未加载",
    plotlyBundle: "strict-csp",
    browser: navigator.userAgent,
    renderer: "等待第一张图实际建立上下文",
    sharedPlotSurfaces: GPU_PLOT_BUDGET,
    fixedTraceSlots: GPU_TRACE_SLOTS,
    newPlotCalls: 0,
    reactCalls: 0,
    fatal: false,
  };
  window.stage35GpuDebug = GPU_DIAGNOSTIC;
  const status = $("#gpuStatus");
  if (GPU_DIAGNOSTIC.plotlyVersion !== "3.7.0") {
    GPU_DIAGNOSTIC.fatal = true;
    throw new Error(
      `Plotly静态资源版本错配：实际加载 ${GPU_DIAGNOSTIC.plotlyVersion}，报告固定要求 3.7.0；` +
      "这不是浏览器WebGL能力问题。"
    );
  }
  status.textContent = `GPU绘图：Plotly ${GPU_DIAGNOSTIC.plotlyVersion} strict；等待第一张图建立实际 ` +
    "WebGL 上下文；全页复用同一个 Plotly GPU 画布。";
  if (!GPU_DIAGNOSTIC.webgl1Api) {
    throw new Error("浏览器没有提供 Plotly 所需的 WebGL 1；本报告坚持 GPU 绘图，不会回退到 CPU/SVG。");
  }
}

function finite(value) {
  return value !== null && value !== "" && Number.isFinite(Number(value));
}

function number(value, digits = 6) {
  if (value === null || value === "") return "—";
  const x = Number(value);
  if (!Number.isFinite(x)) return "—";
  const a = Math.abs(x);
  if ((a !== 0 && a < 0.001) || a >= 1e6) return x.toExponential(5);
  return x.toLocaleString("zh-CN", {maximumFractionDigits: digits});
}

function mean(values) {
  const good = values.filter(finite).map(Number);
  return good.length ? good.reduce((a, b) => a + b, 0) / good.length : NaN;
}

function encode(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => query.set(key, String(value)));
  return query.toString();
}

async function api(path, params = {}) {
  const response = await fetch(`${path}?${encode(params)}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

function sourceText(source) {
  return source.meaning || source.kind || "数据来源说明缺失";
}

function createCard(container, id, heading, source) {
  const card = document.createElement("article");
  card.className = "subject-card";
  card.innerHTML = `<h3>${heading}</h3><p class="subject-source">${source}</p>`;
  container.appendChild(card);
  return card;
}

function groupColor(subjectIndex, frequencyIndex = 0) {
  return COLORS[(subjectIndex * 4 + frequencyIndex) % COLORS.length];
}

function adcLabel(adc) {
  return `ADC${adc}`;
}

function pairLabel(pair) {
  return `ADC${pair[0]}–ADC${pair[1]}`;
}

function groupLabel(labels) {
  return labels.join("、");
}

function markGroupedCard(card, count) {
  card.dataset.subjectCount = String(count);
  return card;
}

function createFigure(card, id, heading, note) {
  const section = document.createElement("section");
  section.className = "figure";
  section.innerHTML = `
    <div class="figure-heading">
      <h4>${heading}</h4>
      <button type="button" class="step-toggle" hidden aria-pressed="false">用阶梯线连接</button>
    </div>
    <div id="${id}" class="plot" aria-label="${heading}"></div>
    <aside class="explanation">
      <dl>
        <div><dt>这些点是什么</dt><dd class="what"></dd></div>
        <div><dt>这个数字从哪里来</dt><dd class="source"></dd></div>
        <div><dt>怎么算</dt><dd><div class="formula-box"></div></dd></div>
        <div><dt>当前算得什么</dt><dd class="calculated"></dd></div>
        <div><dt>怎样理解</dt><dd class="meaning"></dd></div>
      </dl>
    </aside>`;
  card.appendChild(section);
  const set = (selector, text) => { section.querySelector(selector).textContent = text; };
  set(".what", note.what);
  set(".source", note.source);
  set(".calculated", note.calculated);
  set(".meaning", note.meaning);
  const formula = section.querySelector(".formula-box");
  const formulaLines = note.formula.split(/(?:,\\quad|\\qquad)/).map(value => value.trim()).filter(Boolean);
  formulaLines.forEach(value => {
    const line = document.createElement("div");
    line.className = "formula-line";
    if (window.katex) {
      katex.render(value, line, {displayMode: true, throwOnError: false, strict: false});
    } else {
      line.textContent = value;
    }
    formula.appendChild(line);
  });
  return {
    plot: section.querySelector(".plot"),
    calculated: section.querySelector(".calculated"),
    stepToggle: section.querySelector(".step-toggle"),
  };
}

function baseLayout(_title, xTitle, yTitle, extra = {}) {
  return Object.assign({
    title: {text: ""},
    height: GPU_DEFAULT_HEIGHT,
    paper_bgcolor: "#fff", plot_bgcolor: "#fff",
    font: {family: "system-ui, Noto Sans CJK SC, Microsoft YaHei, sans-serif", color: "#18212b"},
    margin: {l: 80, r: 24, t: 92, b: 68},
    hovermode: "closest",
    dragmode: "pan",
    xaxis: {title: {text: xTitle}, gridcolor: "#e4e8ec", zerolinecolor: "#aeb7c0", automargin: true},
    yaxis: {title: {text: yTitle}, gridcolor: "#e4e8ec", zerolinecolor: "#aeb7c0", automargin: true},
    legend: {orientation: "h", yanchor: "bottom", y: 1.02, xanchor: "left", x: 0,
      font: {size: 12}},
  }, extra);
}

function gpuPlaceholder(target) {
  target.replaceChildren();
  const note = document.createElement("button");
  note.type = "button";
  note.className = "gpu-placeholder";
  note.textContent = "点击或滚动到这里，使用 GPU 绘制这张图";
  Object.assign(note.style, {minHeight: "390px", margin: "0", display: "grid",
    width: "100%", placeItems: "center", border: "1px dashed #d8dee5",
    color: "#5d6975", background: "#f5f7f9", cursor: "pointer", font: "inherit"});
  note.addEventListener("click", () => {
    gpuManualTarget = target;
    activateGpuPlot(target).catch(error => console.error(error));
  });
  target.appendChild(note);
}

function ensureGpuSurface() {
  if (gpuSurface) return gpuSurface;
  gpuSurface = document.createElement("div");
  gpuSurface.id = "stage35-shared-gpu-surface";
  gpuSurface.className = "gpu-shared-surface";
  Object.assign(gpuSurface.style, {width: "100%", minHeight: "390px"});
  gpuSurface.addEventListener("webglcontextcreationerror", event => {
    GPU_DIAGNOSTIC.lastContextCreationError = event.statusMessage || "浏览器没有提供详细原因";
  }, true);
  gpuSurface.addEventListener("webglcontextlost", event => {
    GPU_DIAGNOSTIC.lastContextLost = event.statusMessage || "WebGL context lost";
  }, true);
  return gpuSurface;
}

function actualGpuRenderer() {
  if (!gpuSurface) return null;
  for (const canvas of gpuSurface.querySelectorAll("canvas")) {
    let gl = null;
    try { gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl"); }
    catch (_) { gl = null; }
    if (!gl || gl.isContextLost()) continue;
    const debug = gl.getExtension("WEBGL_debug_renderer_info");
    return String(debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
  }
  return null;
}

function updateGpuStatus() {
  const renderer = actualGpuRenderer();
  if (renderer) GPU_DIAGNOSTIC.renderer = renderer;
  $("#gpuStatus").textContent = renderer
    ? `GPU绘图：Plotly ${GPU_DIAGNOSTIC.plotlyVersion} strict，WebGL 已启用；渲染器 ${renderer}；全页复用 1 张 GPU 画布。`
    : `GPU绘图：Plotly ${GPU_DIAGNOSTIC.plotlyVersion} strict，scattergl 已建立；浏览器未公开渲染器名称；全页复用 1 张 GPU 画布。`;
}

function releaseGpuSlot(target, placeholder = true) {
  const spec = gpuPlots.get(target);
  if (!spec) return;
  if (gpuOwner === target) {
    ensureGpuSurface().remove();
    gpuOwner = null;
  }
  if (spec.state !== "error") {
    spec.state = "waiting";
    target.dataset.gpuState = "waiting";
    if (placeholder && target.isConnected) gpuPlaceholder(target);
  }
}

function attachGpuClick(target) {
  const spec = gpuPlots.get(target);
  if (!spec || gpuOwner !== target || spec.state !== "rendered" || !spec.clickBinding) return;
  const surface = ensureGpuSurface();
  if (typeof surface.removeAllListeners === "function") surface.removeAllListeners("plotly_click");
  surface.on("plotly_click", event => {
    const point = event.points && event.points[0];
    if (point) spec.clickBinding.calculated.textContent = spec.clickBinding.callback(point);
  });
}

function fixedGpuTraces(traces) {
  if (traces.length > GPU_TRACE_SLOTS) {
    throw new Error(`一张图包含 ${traces.length} 条曲线，超过固定 GPU 槽位 ${GPU_TRACE_SLOTS}`);
  }
  return Array.from({length: GPU_TRACE_SLOTS}, (_, index) => {
    const trace = traces[index];
    if (!trace) {
      return {type: "scattergl", mode: "markers", x: [], y: [], visible: false,
        uid: `stage35-gpu-trace-${index}`, name: `空槽位 ${index + 1}`};
    }
    const plotlyTrace = Object.assign({}, trace);
    delete plotlyTrace.__stepEligible;
    return Object.assign(plotlyTrace, {
      type: "scattergl", uid: `stage35-gpu-trace-${index}`,
      visible: trace.visible === undefined ? true : trace.visible,
    });
  });
}

async function renderGpuTarget(target) {
  const spec = gpuPlots.get(target);
  if (!spec || gpuFatalError || (gpuOwner === target && spec.state === "rendered")) return;
  const surface = ensureGpuSurface();
  const plotHeight = Number(spec.layout.height) || GPU_DEFAULT_HEIGHT;
  if (gpuOwner && gpuOwner !== target) {
    const previous = gpuOwner;
    const previousSpec = gpuPlots.get(previous);
    surface.remove();
    gpuOwner = null;
    if (previousSpec && previousSpec.state !== "error") {
      previousSpec.state = "waiting";
      previous.dataset.gpuState = "waiting";
      if (previous.isConnected) gpuPlaceholder(previous);
    }
  }
  target.replaceChildren();
  target.style.height = `${plotHeight}px`;
  surface.style.height = `${plotHeight}px`;
  target.appendChild(surface);
  gpuOwner = target;
  spec.state = "rendering";
  target.dataset.gpuState = "rendering";
  try {
    const traces = fixedGpuTraces(spec.traces);
    const config = {
      responsive: true, displaylogo: false, scrollZoom: true, persistGlLayer: true,
      toImageButtonOptions: {format: "png", scale: 2},
    };
    if (!gpuInitialized) {
      GPU_DIAGNOSTIC.newPlotCalls += 1;
      await Plotly.newPlot(surface, traces, spec.layout, config);
      gpuInitialized = true;
    } else {
      GPU_DIAGNOSTIC.reactCalls += 1;
      await Plotly.react(surface, traces, spec.layout, config);
    }
    const warning = surface.querySelector(".no-webgl") ||
      surface.textContent.includes("WebGL is not supported by your browser");
    if (warning) {
      throw new Error(`Plotly ${GPU_DIAGNOSTIC.plotlyVersion} 无法建立WebGL上下文；页面已停止自动重试以避免上下文泄漏；诊断=${JSON.stringify(GPU_DIAGNOSTIC)}`);
    }
    if (!gpuPlots.has(target) || gpuOwner !== target) return;
    spec.state = "rendered";
    target.dataset.gpuState = "rendered";
    updateGpuStatus();
    attachGpuClick(target);
  } catch (error) {
    gpuFatalError = error;
    GPU_DIAGNOSTIC.fatal = true;
    spec.state = "error";
    target.dataset.gpuState = "error";
    if (gpuOwner === target) {
      surface.remove();
      gpuOwner = null;
    }
    target.textContent = `GPU 绘图失败：${error.message}`;
    throw error;
  }
}

function activateGpuPlot(target) {
  const spec = gpuPlots.get(target);
  if (!spec || gpuFatalError || spec.state === "error") return Promise.resolve();
  gpuDesiredTarget = target;
  gpuQueue = gpuQueue.catch(() => {}).then(async () => {
    const desired = gpuDesiredTarget;
    gpuDesiredTarget = null;
    if (desired && gpuPlots.has(desired)) await renderGpuTarget(desired);
  });
  return gpuQueue;
}

function scheduleVisibleGpuPlot() {
  if (gpuObserverFrame) cancelAnimationFrame(gpuObserverFrame);
  gpuObserverFrame = requestAnimationFrame(() => {
    gpuObserverFrame = 0;
    const visible = Array.from(gpuPlots.entries()).filter(([, spec]) => spec.visible);
    if (gpuManualTarget && !visible.some(([target]) => target === gpuManualTarget)) {
      gpuManualTarget = null;
    }
    const viewportCenter = innerHeight / 2;
    const target = (gpuManualTarget && gpuPlots.get(gpuManualTarget)?.visible)
      ? gpuManualTarget
      : visible.sort(([a], [b]) =>
          Math.abs((a.getBoundingClientRect().top + a.getBoundingClientRect().bottom) / 2 - viewportCenter) -
          Math.abs((b.getBoundingClientRect().top + b.getBoundingClientRect().bottom) / 2 - viewportCenter)
        )[0]?.[0];
    if (target) activateGpuPlot(target).catch(error => console.error(error));
    else if (gpuOwner) releaseGpuSlot(gpuOwner);
  });
}

const gpuObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    const spec = gpuPlots.get(entry.target);
    if (!spec) return;
    spec.visible = entry.isIntersecting;
  });
  scheduleVisibleGpuPlot();
}, {root: null, rootMargin: "0px", threshold: 0.1});

async function draw(target, traces, layout) {
  if (!traces.length || traces.some(trace => trace.type !== "scattergl")) {
    throw new Error("检测到非 GPU 曲线；本报告禁止回退到 SVG/CPU 绘图");
  }
  const stepIndices = traces.flatMap((trace, index) => trace.__stepEligible ? [index] : []);
  const legendEntries = traces.filter(trace => trace.showlegend !== false && trace.visible !== false).length;
  const legendRows = Math.ceil(legendEntries / 3);
  if (legendRows > 2) {
    const extra = (legendRows - 2) * 24;
    layout = Object.assign({}, layout, {
      height: (Number(layout.height) || GPU_DEFAULT_HEIGHT) + extra,
      margin: Object.assign({}, layout.margin, {t: (Number(layout.margin?.t) || 92) + extra}),
    });
  }
  const spec = {
    traces, layout, state: "waiting", visible: false, clickBinding: null,
    stepIndices, stepEnabled: false,
  };
  target.style.height = `${Number(layout.height) || GPU_DEFAULT_HEIGHT}px`;
  gpuPlots.set(target, spec);
  target.dataset.gpuRenderer = "scattergl";
  target.dataset.gpuState = "waiting";
  gpuPlaceholder(target);
  gpuObserver.observe(target);
  const stepToggle = target.closest(".figure")?.querySelector(".step-toggle");
  if (stepToggle && stepIndices.length) {
    stepToggle.hidden = false;
    stepToggle.onclick = () => toggleStepLines(target);
  }
  const rect = target.getBoundingClientRect();
  if (rect.bottom >= 0 && rect.top <= innerHeight) scheduleVisibleGpuPlot();
}

function pointTrace(x, y, name, color, extra = {}) {
  const {marker: extraMarker = {}, stepEligible = true, ...rest} = extra;
  return Object.assign({type: "scattergl", mode: "markers", x, y, name,
    marker: {size: x.length > 5000 ? 3 : 5, color, opacity: 0.72,
      symbol: "x", ...extraMarker}, __stepEligible: stepEligible}, rest);
}

function translucentColor(color, alpha = 0.24) {
  const match = /^#([0-9a-f]{6})$/i.exec(String(color));
  if (!match) return color;
  const value = Number.parseInt(match[1], 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

async function toggleStepLines(target) {
  const spec = gpuPlots.get(target);
  if (!spec || !spec.stepIndices.length) return;
  spec.stepEnabled = !spec.stepEnabled;
  spec.stepIndices.forEach(index => {
    const trace = spec.traces[index];
    trace.mode = spec.stepEnabled ? "lines+markers" : "markers";
    trace.line = Object.assign({}, trace.line, {
      color: translucentColor(trace.marker?.color),
      width: 0.8,
      shape: "hv",
    });
  });
  const button = target.closest(".figure")?.querySelector(".step-toggle");
  if (button) {
    button.setAttribute("aria-pressed", String(spec.stepEnabled));
    button.textContent = spec.stepEnabled ? "只看叉形散点" : "用阶梯线连接";
  }
  if (gpuOwner === target && spec.state === "rendered") {
    GPU_DIAGNOSTIC.restyleCalls = (GPU_DIAGNOSTIC.restyleCalls || 0) + 1;
    await Plotly.restyle(ensureGpuSurface(), {
      mode: spec.stepEnabled ? "lines+markers" : "markers",
      "line.shape": "hv",
      "line.width": 0.8,
      "line.color": spec.stepIndices.map(index => translucentColor(spec.traces[index].marker?.color)),
    }, spec.stepIndices);
  }
}

function binsParam() {
  return state.bins.join(",");
}

function rfLabel(row) {
  return `${Number(row.rf_mhz).toFixed(6)} MHz (bin ${row.global_bin})`;
}

function signedInteger(value) {
  const integer = Number(value);
  return integer > 0 ? `+${integer}` : String(integer);
}

function commonParams() {
  return {bins: binsParam(), capture: META.spec_capture, bucket: state.fengineShort};
}

function bindClick(plot, calculated, callback) {
  const spec = gpuPlots.get(plot);
  if (!spec) throw new Error("GPU 图尚未登记");
  spec.clickBinding = {calculated, callback};
  attachGpuClick(plot);
}

async function renderTimeSingle(adcs, guard = () => true) {
  const datasets = await Promise.all(adcs.map(async adc => {
    const [raw, bucketed, long] = await Promise.all([
      api("/api/v2/timeseries", {domain: "time_single", adc, capture: state.time,
        bucket: "raw", start_sample: state.timeStart}),
      api("/api/v2/timeseries", {domain: "time_single", adc, capture: state.time,
        bucket: state.timeShort}),
      api("/api/v2/timeseries", {domain: "time_long_single", adc,
        cadence_ms: state.timeLongMs}),
    ]);
    return {adc, label: adcLabel(adc), raw, bucketed, long};
  }));
  if (!guard()) return;
  const labels = datasets.map(item => item.label);
  const first = datasets[0];
  const card = markGroupedCard(createCard($("#singleTimeCards"), "single-time-group",
    groupLabel(labels), sourceText(first.raw.source)), datasets.length);

  let figure = createFigure(card, `single-time-raw-page-${state.page}`, "未经平均的 4096 个连续 I/Q 整数读数", {
    what: `同一幅图叠加 ${groupLabel(labels)}。小叉是 I，空心小三角是 Q；每个标记对应一个 TIME_ONLY 样点，都没有平均。`,
    source: sourceText(first.raw.source), formula: first.raw.formula,
    calculated: datasets.map(({label, raw}) => `${label}：平均 I=${number(mean(raw.i_adu))} ADU，平均 Q=${number(mean(raw.q_adu))} ADU`).join("；") + "。点击任一点可看所属 ADC 和实值。",
    meaning: "这些是 RFDC 下变频和抽取后输出的 I/Q 有符号整数。多数值集中在约 −10～+10，只说明当前输入较小、没有占满 16 位范围；它不是 ADC 的 3.84 GS/s 原始转换码。",
  });
  const rawTraces = [];
  datasets.forEach(({adc, label, raw}, subjectIndex) => {
    const color = groupColor(subjectIndex);
    rawTraces.push(pointTrace(raw.time_us, raw.i_adu, `${label} · I`, color, {
      marker: {color, opacity: .82},
      customdata: raw.i_adu.map((v, i) => [adc, i + raw.calculation.start_sample, "I", signedInteger(v)]),
      hovertemplate: `${label} · I<br>时间 %{x:.6f} µs<br>样点编号 %{customdata[1]:,d}<br>I 读数 %{customdata[3]}（有符号16位整数）<extra></extra>`,
    }));
    rawTraces.push(pointTrace(raw.time_us, raw.q_adu, `${label} · Q`, color, {
      marker: {color, opacity: .55, symbol: "triangle-up-open"},
      customdata: raw.q_adu.map((v, i) => [adc, i + raw.calculation.start_sample, "Q", signedInteger(v)]),
      hovertemplate: `${label} · Q<br>时间 %{x:.6f} µs<br>样点编号 %{customdata[1]:,d}<br>Q 读数 %{customdata[3]}（有符号16位整数）<extra></extra>`,
    }));
  });
  await draw(figure.plot, rawTraces, baseLayout("TIME_ONLY 原样点同图比较", "相对数据段起点的时间 (µs)", "I / Q 整数读数 (ADU)"));
  bindClick(figure.plot, figure.calculated, p => `ADC${p.customdata[0]} · ${p.customdata[2]}：时间 ${Number(p.x).toFixed(6)} µs；样点编号 ${Number(p.customdata[1]).toLocaleString()}；读数 ${p.customdata[3]}（有符号16位整数，未经平均）。`);

  const width = first.bucketed.calculation.bucket_samples;
  figure = createFigure(card, `single-time-avg-page-${state.page}`, "分桶后的平均 I 和平均 Q", {
    what: `同一幅图叠加 ${groupLabel(labels)}；每个点是连续 ${width.toLocaleString()} 个 TIME_ONLY 样点分别求出的平均 I 或平均 Q。`,
    source: sourceText(first.bucketed.source), formula: first.bucketed.formula,
    calculated: datasets.map(({label, bucketed}) => `${label}：${bucketed.calculation.points.toLocaleString()} 个桶，平均 I=${number(mean(bucketed.i_adu))} ADU、平均 Q=${number(mean(bucketed.q_adu))} ADU`).join("；") + "。",
    meaning: `这里先取得有正有负的整数 I/Q，再把每 ${width.toLocaleString()} 个整数求平均，所以结果可以是小数；随机噪声经过更多样点平均后应更靠近零。没有使用 RMS。`,
  });
  const averageTraces = [];
  datasets.forEach(({label, bucketed}, subjectIndex) => {
    const color = groupColor(subjectIndex);
    averageTraces.push(pointTrace(bucketed.time_us, bucketed.i_adu, `${label} · 平均 I`, color,
      {marker: {color, opacity: .82}}));
    averageTraces.push(pointTrace(bucketed.time_us, bucketed.q_adu, `${label} · 平均 Q`, color,
      {marker: {color, opacity: .55, symbol: "triangle-up-open"}}));
  });
  await draw(figure.plot, averageTraces, baseLayout("TIME_ONLY 分桶平均同图比较", "相对数据段起点的时间 (µs)", "平均 I / Q (ADU，可为小数)"));

  const longIqTraces = [];
  datasets.forEach(({label, long}, subjectIndex) => {
    const color = groupColor(subjectIndex);
    longIqTraces.push(pointTrace(long.time_s, long.mean_i_adu, `${label} · 平均 I`, color,
      {marker: {color, opacity: .82}}));
    longIqTraces.push(pointTrace(long.time_s, long.mean_q_adu, `${label} · 平均 Q`, color,
      {marker: {color, opacity: .55, symbol: "triangle-up-open"}}));
  });
  const firstLong = first.long;
  figure = createFigure(card, `single-time-long-iq-page-${state.page}`,
    `TIME_ONLY 900秒 I/Q中心（每点 ${firstLong.cadence_ms} ms）`, {
      what: `同一幅图叠加 ${groupLabel(labels)}；小叉是平均I，空心小三角是平均Q。`,
      source: sourceText(firstLong.source), formula: firstLong.formula,
      calculated: datasets.map(({label, long}) => `${label}：${long.calculation.display_points.toLocaleString()}点，整段平均I=${number(mean(long.mean_i_adu))} ADU、平均Q=${number(mean(long.mean_q_adu))} ADU`).join("；") + "。",
      meaning: "这两条量看900秒内数字零点是否缓慢移动；它们不是噪声幅度，也没有频率bin。",
    });
  await draw(figure.plot, longIqTraces, baseLayout("TIME_ONLY 900秒 I/Q中心同图比较", "时间 (s)", "平均 I / Q (ADU)"));

  const longPowerTraces = [];
  datasets.forEach(({label, long}, subjectIndex) => {
    const color = groupColor(subjectIndex);
    longPowerTraces.push(pointTrace(long.time_s, long.mean_power_adu2, `${label} · 平均数字功率`, color, {
      customdata: long.mean_power_adu2.map((value, index) => [label, index, value, long.n_valid[index], long.cadence_ms]),
    }));
  });
  figure = createFigure(card, `single-time-long-power-page-${state.page}`,
    `TIME_ONLY 900秒平均数字功率（每点 ${firstLong.cadence_ms} ms）`, {
      what: `每个叉是该时间桶内所有TIME_ONLY整数先逐样点计算I²+Q²，再求平均；同图叠加 ${groupLabel(labels)}。`,
      source: sourceText(firstLong.source), formula: firstLong.formula,
      calculated: datasets.map(({label, long}) => `${label}：${long.calculation.display_points.toLocaleString()}点，整段平均数字功率=${number(mean(long.mean_power_adu2))} ADU²`).join("；") + "。点击点可看有效样本数。",
      meaning: "这张图看宽带TIME_ONLY噪声强弱是否随900秒缓慢变化。它是mean(I²+Q²)，不是RMS，也没有换算成温度。",
    });
  await draw(figure.plot, longPowerTraces, baseLayout("TIME_ONLY 900秒平均数字功率同图比较", "时间 (s)", "平均 I²+Q² (ADU²)"));
  bindClick(figure.plot, figure.calculated, point => {
    const value = point.customdata;
    return `${value[0]}，时间桶 ${value[1]}，每点 ${value[4]} ms：${Number(value[3]).toLocaleString()}个有效样点，平均I²+Q²=${number(value[2])} ADU²。`;
  });
}

async function shortSingleFigure(card, datasets, id, heading, meaning, powerOnly = false) {
  const traces = [];
  datasets.forEach(({label: subject, data}, subjectIndex) => {
    data.series.forEach((row, frequencyIndex) => {
      const frequency = rfLabel(row);
      const color = groupColor(subjectIndex, frequencyIndex);
      if (!powerOnly) {
        const rawInteger = data.domain === "fengine_raw_single" && data.bucket_frames === 1;
        const iExtra = {marker: {size: 3, color, opacity: .72}};
        const qExtra = {marker: {size: 4, color, opacity: .55, symbol: "triangle-up-open"}};
        if (rawInteger) {
          iExtra.customdata = row.i.map((v, n) => [subject, row.global_bin, row.rf_mhz, n, signedInteger(v)]);
          qExtra.customdata = row.q.map((v, n) => [subject, row.global_bin, row.rf_mhz, n, signedInteger(v)]);
          iExtra.hovertemplate = `${subject} · ${frequency} · I<br>时间 %{x:.6f} ms<br>F-engine 帧 %{customdata[3]:,d}<br>I 读数 %{customdata[4]}（有符号16位整数）<extra></extra>`;
          qExtra.hovertemplate = `${subject} · ${frequency} · Q<br>时间 %{x:.6f} ms<br>F-engine 帧 %{customdata[3]:,d}<br>Q 读数 %{customdata[4]}（有符号16位整数）<extra></extra>`;
        }
        traces.push(pointTrace(data.time_ms, row.i, `${subject} · ${frequency} · I`, color, iExtra));
        traces.push(pointTrace(data.time_ms, row.q, `${subject} · ${frequency} · Q`, color, qExtra));
      } else {
        traces.push(pointTrace(data.time_ms, row.power, `${subject} · ${frequency}`, color, {
          customdata: row.power.map((v, n) => [subject, row.global_bin, row.rf_mhz, n, v, data.bucket_frames]),
        }));
      }
    });
  });
  const firstData = datasets[0].data;
  const current = datasets.map(({label, data}) => {
    const first = data.series[0];
    return powerOnly
      ? `${label} · ${rfLabel(first)}：${data.calculation.output_points.toLocaleString()} 点，平均功率=${number(first.mean_power)} ${data.power_unit}`
      : `${label} · ${rfLabel(first)}：平均 I=${number(mean(first.i))} ${data.iq_unit}，平均 Q=${number(mean(first.q))} ${data.iq_unit}`;
  }).join("；") + "。";
  const figure = createFigure(card, id, heading, {
    what: `同一幅图叠加 ${groupLabel(datasets.map(item => item.label))}。${firstData.point_definition}`,
    source: sourceText(firstData.source), formula: firstData.formula, calculated: current, meaning,
  });
  const yTitle = powerOnly ? `平均 I²+Q² (${firstData.power_unit})` : `I / Q (${firstData.iq_unit})`;
  await draw(figure.plot, traces, baseLayout(heading, "相对采集起点的时间 (ms)", yTitle));
  if (powerOnly) bindClick(figure.plot, figure.calculated, p => {
    const d = p.customdata;
    return `${d[0]} · ${Number(d[2]).toFixed(6)} MHz (bin ${d[1]})，显示点 ${d[3]}：按 ${d[5]} 帧桶计算，平均 I²+Q²=${number(d[4])} ${firstData.power_unit}。`;
  });
}

async function renderFengineSingle(adcs, guard = () => true) {
  const params = commonParams();
  const datasets = await Promise.all(adcs.map(async adc => {
    const [raw, averaged, long, fft] = await Promise.all([
      api("/api/v2/timeseries", {...params, domain: "fengine_raw_single", adc, bucket: 1}),
      api("/api/v2/timeseries", {...params, domain: "fengine_raw_single", adc}),
      api("/api/v2/timeseries", {domain: "fengine_long_single", adc, bins: binsParam(), scan: state.selfScan, cadence_ms: state.singleMs}),
      api("/api/v2/timeseries", {...params, domain: "time_fft_single", adc, capture: state.fftCapture}),
    ]);
    return {adc, label: adcLabel(adc), raw, averaged, long, fft};
  }));
  if (!guard()) return;
  const labels = datasets.map(item => item.label);
  const card = markGroupedCard(createCard($("#singleFengineCards"), "single-fengine-group",
    groupLabel(labels), sourceText(datasets[0].raw.source)), datasets.length);
  await shortSingleFigure(card, datasets.map(item => ({label: item.label, data: item.raw})),
    `single-spec-iq-page-${state.page}`, "F-engine 每帧原始 I/Q count",
    "一个频率通道每 12.8 µs 产生一个复数。这里不平均，所以能直接看到通道化后的有符号整数怎样跳动。", false);
  await shortSingleFigure(card, datasets.map(item => ({label: item.label, data: item.raw})),
    `single-spec-power-page-${state.page}`, "同一批原始帧逐帧计算功率",
    "功率必须先对每一帧计算 I²+Q²，再平均。不能先平均 I/Q 再平方。", true);
  if (state.fengineShort !== 1) await shortSingleFigure(card, datasets.map(item => ({label: item.label, data: item.averaged})),
    `single-spec-avg-page-${state.page}`, `${state.fengineShort} 帧平均后的 F-engine 功率`,
    `每个点使用相邻 ${state.fengineShort} 帧，但没有混合相邻频率通道；可与上面的逐帧散点直接比较。`, true);

  const longTraces = [];
  datasets.forEach(({label, long}, subjectIndex) => long.series.forEach((row, frequencyIndex) => {
    const color = groupColor(subjectIndex, frequencyIndex);
    longTraces.push(pointTrace(long.time_s, row.power_count2, `${label} · ${rfLabel(row)}`, color, {
      customdata: row.power_count2.map((v, n) => [label, row.global_bin, row.rf_mhz, n, v, row.n_valid[n]]),
    }));
  }));
  const firstLong = datasets[0].long;
  let figure = createFigure(card, `single-long-page-${state.page}`, `900 秒 F-engine 功率（每点 ${firstLong.cadence_ms} ms）`, {
    what: `同一幅图叠加 ${groupLabel(labels)}。${firstLong.point_definition}`,
    source: sourceText(firstLong.source), formula: firstLong.formula,
    calculated: datasets.map(({label, long}) => `${label} · ${rfLabel(long.series[0])}：${long.calculation.display_points.toLocaleString()} 点，全扫描加权平均=${number(long.series[0].scan_mean_power_count2)} count²`).join("；") + "。点击点可看实值。",
    meaning: "横轴拉到 900 秒后，可以直接比较各 ADC 的功率背景是否缓慢漂移；纵轴仍是数字功率 count²，没有换算成温度或流量密度。",
  });
  await draw(figure.plot, longTraces, baseLayout(`${state.selfScan} 段 900 秒功率同图比较`, "时间 (s)", "平均 I²+Q² (count²)"));
  bindClick(figure.plot, figure.calculated, p => {
    const d = p.customdata;
    return `${d[0]} · ${Number(d[2]).toFixed(6)} MHz (bin ${d[1]})，时间桶 ${d[3]}：${Number(d[5]).toLocaleString()} 个有效频谱，平均功率=${number(d[4])} count²。`;
  });

  await shortSingleFigure(card, datasets.map(item => ({label: item.label, data: item.fft})),
    `single-fft-page-${state.page}`, "TIME_ONLY 的普通 4096 点 Hann FFT 参照",
    "这是另一段 TIME_ONLY 数据做的普通 FFT。采集时间和生产 PFB 滤波器都不同，只用来看频率附近的大致变化，绝不作绝对幅度对齐。", true);
}

async function allanFigure(card, datasets, id, heading, subjectText) {
  const traces = [];
  let whiteLegendShown = false;
  datasets.forEach(({label: subject, data}, subjectIndex) => {
    data.series.forEach((row, frequencyIndex) => {
      const color = groupColor(subjectIndex, frequencyIndex);
      const x = row.points.map(p => p.tau_s);
      const custom = row.points.map(p => [subject, row.global_bin, row.rf_mhz, p.N, p.m, p.K, p.tau_s,
        p.sum_squared_difference, p.value]);
      traces.push({type: "scattergl", mode: "lines+markers", x, y: row.points.map(p => p.value),
        name: `${subject} · ${rfLabel(row)} · 实测`, line: {color, width: 2},
        marker: {size: 7, color, symbol: "x"}, customdata: custom});
      traces.push({type: "scattergl", mode: "lines", x, y: row.points.map(p => p.white_reference),
        name: "虚线：如果是白噪声，应按此速度下降", showlegend: !whiteLegendShown,
        line: {color, dash: "dash", width: 2}, hoverinfo: "skip"});
      whiteLegendShown = true;
    });
  });
  const firstData = datasets[0].data;
  const first = firstData.series[0].points[0];
  const formText = firstData.form === "variance" ? "Allan 方差" : "Allan 方差的平方根";
  const scaleText = firstData.scale === "relative" ? "相对百分比" : "原始数字功率";
  const figure = createFigure(card, id, heading, {
    what: `${subjectText}。同一幅图叠加 ${groupLabel(datasets.map(item => item.label))}；叉形实线由测量数据计算，同色虚线不是测量数据。`,
    source: sourceText(firstData.source), formula: `${firstData.formula}\\qquad ${firstData.white_formula}`,
    calculated: `当前显示 ${formText}、${scaleText}。以 ${datasets[0].label} 首点为例：τ=${number(first.tau_s)} s，N=${first.N.toLocaleString()}，m=${first.m}，K=${first.K.toLocaleString()}，平方差之和=${number(first.sum_squared_difference)}，最终值=${number(first.value)} ${firstData.unit}。点击任一实测点看该对象的全过程。`,
    meaning: "曲线若像虚线一样持续下降，说明延长积分仍有效；实线变平或抬头，说明继续积分没有按白噪声的理想速度获益。",
  });
  await draw(figure.plot, traces, baseLayout(heading, "相邻平均窗口长度 τ (s)", `${formText} (${firstData.unit})`, {
    xaxis: {title: {text: "相邻平均窗口长度 τ (s)"}, type: "log", gridcolor: "#e4e8ec", automargin: true},
    yaxis: {title: {text: `${formText} (${firstData.unit})`}, type: "log", gridcolor: "#e4e8ec", automargin: true},
  }));
  bindClick(figure.plot, figure.calculated, p => {
    if (!p.customdata) return "虚线不是测量点；它从同色实测首点锚定，只表示白噪声应下降的速度。";
    const d = p.customdata;
    return `${d[0]} · ${Number(d[2]).toFixed(6)} MHz (bin ${d[1]})：N=${Number(d[3]).toLocaleString()}；τ=${number(d[6])} s，m=${d[4]}；K=N−2m+1=${Number(d[5]).toLocaleString()}；平方差之和=${number(d[7])}；除以 2K${firstData.form === "square_root" ? " 后再开平方" : ""}，得到 ${number(d[8])} ${firstData.unit}。`;
  });
}

async function renderAllanSingle(adcs, guard = () => true) {
  const datasets = await Promise.all(adcs.map(async adc => ({
    label: adcLabel(adc),
    data: await api("/api/v2/allan", {subject: "single", adc, bins: binsParam(), scan: state.allanScan,
      form: state.allanForm, scale: state.allanScale}),
  })));
  if (!guard()) return;
  const card = markGroupedCard(createCard($("#singleAllanCards"), "single-allan-group",
    groupLabel(datasets.map(item => item.label)), sourceText(datasets[0].data.source)), datasets.length);
  await allanFigure(card, datasets, `single-allan-page-${state.page}`, "F-engine Allan 方差同图比较",
    "每条实线从相应 ADC、相应频率的 900 秒 F-engine 10 ms 平均功率序列开始，比较相邻的两个时间窗口");
}

async function visibilityFigure(card, datasets, id, heading, meaning) {
  const traces = [];
  const firstData = datasets[0].data;
  const firstX = firstData.time_us || firstData.time_ms || firstData.time_s;
  const xTitle = firstData.time_us ? "相对数据段起点的时间 (µs)" : firstData.time_ms ? "相对采集起点的时间 (ms)" : "时间 (s)";
  datasets.forEach(({label: subject, data}, subjectIndex) => {
    const x = data.time_us || data.time_ms || data.time_s;
    const rows = data.series || [{global_bin: null, rf_mhz: null, amplitude: data.amplitude_adu2,
      phase_deg: data.phase_deg, gamma: data.gamma, phase_reliable: data.phase_reliable}];
    rows.forEach((row, frequencyIndex) => {
      const frequency = row.global_bin === null ? "" : ` · ${rfLabel(row)}`;
      const label = `${subject}${frequency}`;
      const color = groupColor(subjectIndex, frequencyIndex);
      const amplitude = row.amplitude || row.amplitude_count2 || data.amplitude_adu2;
      traces.push(pointTrace(x, amplitude, `${label} · 幅度`, color, {
        xaxis: "x", yaxis: "y", customdata: amplitude.map((v, n) => [subject, row.global_bin,
          row.rf_mhz, n, v, row.phase_deg[n], row.gamma[n], row.phase_reliable[n]])}));
      const reliableX = [], reliableY = [], weakX = [], weakY = [];
      row.phase_deg.forEach((value, n) => {
        if (row.phase_reliable[n]) { reliableX.push(x[n]); reliableY.push(value); }
        else { weakX.push(x[n]); weakY.push(value); }
      });
      traces.push(pointTrace(reliableX, reliableY, `${label} · 相位`, color,
        {xaxis: "x2", yaxis: "y2", showlegend: false,
          marker: {color, opacity: .72, symbol: "triangle-up-open"}}));
      traces.push(pointTrace(weakX, weakY, `${label} · 弱相关相位（不可解释）`, "#aeb5bc",
        {xaxis: "x2", yaxis: "y2", showlegend: false,
          marker: {size: 4, color: "#aeb5bc", opacity: .52, symbol: "triangle-up-open"}}));
    });
  });
  const firstRows = firstData.series || [{global_bin: null, rf_mhz: null, amplitude: firstData.amplitude_adu2,
    phase_deg: firstData.phase_deg, gamma: firstData.gamma, phase_reliable: firstData.phase_reliable}];
  const first = firstRows[0];
  const amplitude = first.amplitude || first.amplitude_count2 || firstData.amplitude_adu2;
  const reliableCount = first.phase_reliable.filter(Boolean).length;
  const unit = firstData.amplitude_unit || "ADU²";
  const figure = createFigure(card, id, heading, {
    what: `同一幅图叠加 ${groupLabel(datasets.map(item => item.label))}。${firstData.point_definition}`,
    source: sourceText(firstData.source), formula: firstData.formula,
    calculated: `${datasets[0].label}${first.global_bin === null ? "" : ` · ${rfLabel(first)}`}：${amplitude.length.toLocaleString()} 点，平均复可见度幅度=${number(mean(amplitude))} ${unit}，其中 ${reliableCount.toLocaleString()} 点达到 |相关系数|≥${firstData.phase_gate_gamma} 的相位提示门限。点击幅度点可看所属 ADC 对和实值。`,
    meaning: `${meaning} 灰色相位表示相关幅度太弱，角度主要受噪声摆布，不可作天文相位解释。`,
  });
  await draw(figure.plot, traces, {
    ...baseLayout(heading, xTitle, `复可见度幅度 (${unit})`),
    grid: {rows: 2, columns: 1, pattern: "independent", roworder: "top to bottom"},
    xaxis: {title: {text: ""}, gridcolor: "#e4e8ec", domain: [0, 1], automargin: true},
    yaxis: {title: {text: `复可见度幅度 (${unit})`}, gridcolor: "#e4e8ec", domain: [.57, 1], automargin: true},
    xaxis2: {title: {text: xTitle}, gridcolor: "#e4e8ec", domain: [0, 1], automargin: true},
    yaxis2: {title: {text: "相位 (度)"}, gridcolor: "#e4e8ec", range: [-180, 180], domain: [0, .4], automargin: true},
    height: 620,
  });
  bindClick(figure.plot, figure.calculated, p => {
    if (!p.customdata) return "该点是相位显示点。灰色点没有达到相关幅度门限，不作天文相位解释。";
    const d = p.customdata;
    const freq = d[1] === null ? d[0] : `${d[0]} · ${Number(d[2]).toFixed(6)} MHz (bin ${d[1]})`;
    return `${freq}，点 ${d[3]}：复可见度幅度=${number(d[4])} ${unit}，相位=${number(d[5])}°，|相关系数|=${number(d[6])}；${d[7] ? "达到显示门限，但仍只是独立 50 Ω 的仪器伪相关。" : "低于门限，相位已变灰，不可作天文相位解释。"}`;
  });
}

async function renderFenginePair(pairs, guard = () => true) {
  const datasets = await Promise.all(pairs.map(async pair => {
    const name = pair.join("-");
    const params = {...commonParams(), pair: name};
    const [raw, averaged, long] = await Promise.all([
      api("/api/v2/timeseries", {...params, domain: "fengine_raw_pair", bucket: 1}),
      api("/api/v2/timeseries", {...params, domain: "fengine_raw_pair"}),
      api("/api/v2/timeseries", {domain: "fengine_long_pair", pair: name, bins: binsParam(), cadence_ms: state.pairVisibilityMs}),
    ]);
    return {pair, label: pairLabel(pair), raw, averaged, long};
  }));
  if (!guard()) return;
  const labels = datasets.map(item => item.label);
  const card = markGroupedCard(createCard($("#pairFengineCards"), "pair-fengine-group",
    groupLabel(labels), sourceText(datasets[0].raw.source)), datasets.length);
  await visibilityFigure(card, datasets.map(item => ({label: item.label, data: item.raw})),
    `pair-spec-raw-page-${state.page}`, "F-engine 每帧的瞬时复乘",
    "一个点只由同频、同帧的两个复数相乘得到，还没有形成可靠相关平均。");
  if (state.fengineShort !== 1) await visibilityFigure(card, datasets.map(item => ({label: item.label, data: item.averaged})),
    `pair-spec-avg-page-${state.page}`, `${state.fengineShort} 个 F-engine 帧的复数平均`,
    "这里先逐帧复乘，再把相邻帧的实部和虚部分别平均。");
  await visibilityFigure(card, datasets.map(item => ({label: item.label, data: item.long})),
    `pair-long-page-${state.page}`, `900 秒 F-engine 复可见度（每点 ${state.pairVisibilityMs} ms）`,
    state.pairVisibilityMs === 100
      ? "这是正式采集中直接保存的全 4096 通道 100 ms 产品。"
      : "每个 1 s 点由同批十个 100 ms 产品按有效频谱数加权合并，不是另一遍采集。");
}

async function renderAllanPair(pairs, guard = () => true) {
  const datasets = await Promise.all(pairs.map(async pair => ({
    label: pairLabel(pair),
    data: await api("/api/v2/allan", {subject: "pair", pair: pair.join("-"), bins: binsParam(),
      cadence_ms: state.pairAllanMs, form: state.allanForm, scale: state.allanScale}),
  })));
  if (!guard()) return;
  const card = markGroupedCard(createCard($("#pairAllanCards"), "pair-allan-group",
    groupLabel(datasets.map(item => item.label)), sourceText(datasets[0].data.source)), datasets.length);
  await allanFigure(card, datasets, `pair-allan-page-${state.page}`, "复可见度 Allan 方差同图比较",
    "每条实线从相应 ADC 对、相应频率的 900 秒完整复可见度序列开始；相邻窗口比较完整复数向量，使用 |Y₂−Y₁|²，不直接相减会绕回的相位角");
}

function selected(name) {
  return $$(`input[name="${name}"]:checked`).map(input => input.value);
}

function readControls(resetPage = true) {
  const bins = $("#frequencies").value.split(",").map(x => x.trim()).filter(Boolean);
  if (!bins.length || bins.length > 4) throw new Error("频率必须选择 1–4 个");
  state.bins = bins;
  state.time = $("#timeCapture").value;
  state.timeShort = Number($("#timeShortBucket").value);
  state.timeLongMs = Number($("#timeLongCadence").value);
  state.timeStart = Number($("#timeStart").value);
  state.fengineShort = Number($("#fengineShortBucket").value);
  state.selfScan = $("#selfScan").value;
  state.singleMs = Number($("#singleCadence").value);
  state.fftCapture = $("#fftCapture").value;
  state.pairVisibilityMs = Number($("#pairVisibilityCadence").value);
  state.allanScan = $("#allanScan").value;
  state.pairAllanMs = Number($("#pairAllanCadence").value);
  state.allanForm = $("#allanForm").value;
  state.allanScale = $("#allanScale").value;
  state.adcs = selected("adc").map(Number);
  state.pairs = selected("pair").map(x => x.split("-").map(Number));
  if (state.mode === "single" && !state.adcs.length) throw new Error("至少选择一个 ADC");
  if (state.mode === "pair" && !state.pairs.length) throw new Error("至少选择一个 ADC 对");
  if (resetPage) state.page = 0;
}

function writeUrl() {
  const url = new URL(location.href);
  const values = {
    mode: state.mode, adcs: state.adcs.join(","), pairs: state.pairs.map(x => x.join("-")).join(","),
    bins: state.bins.join(","), time_capture: state.time, time_short: state.timeShort,
    time_long_ms: state.timeLongMs, time_start: state.timeStart,
    fengine_short: state.fengineShort, self_scan: state.selfScan, self_ms: state.singleMs,
    fft_capture: state.fftCapture, pair_visibility_ms: state.pairVisibilityMs,
    allan_scan: state.allanScan, pair_allan_ms: state.pairAllanMs,
    allan_form: state.allanForm, allan_scale: state.allanScale, page: state.page,
  };
  Object.entries(values).forEach(([key, value]) => url.searchParams.set(key, String(value)));
  ["time", "short", "scan", "single_ms", "pair_ms"].forEach(key => url.searchParams.delete(key));
  history.replaceState(null, "", url);
}

function restoreUrl() {
  const p = new URL(location.href).searchParams;
  state.mode = p.get("mode") === "pair" ? "pair" : "single";
  state.page = Math.max(0, Number(p.get("page") || 0));
  return p;
}

function setMode(mode, render = true) {
  state.mode = mode;
  $("#singleTab").classList.toggle("active", mode === "single");
  $("#pairTab").classList.toggle("active", mode === "pair");
  $("#singleView").hidden = mode !== "single";
  $("#pairView").hidden = mode !== "pair";
  $("#adcChoices").hidden = mode !== "single";
  $("#pairChoicesWrap").hidden = mode !== "pair";
  $("#timeControls").hidden = mode !== "single";
  $("#singleFengineControls").hidden = mode !== "single";
  $("#pairFengineControls").hidden = mode !== "pair";
  $("#singleAllanControls").hidden = mode !== "single";
  $("#pairAllanControls").hidden = mode !== "pair";
  $("#fengineChapterNumber").textContent = mode === "single" ? "2" : "1";
  $("#allanChapterNumber").textContent = mode === "single" ? "3" : "2";
  $("#fengineScope").textContent = mode === "single" ? "只刷新第2章。" : "只刷新第1章。";
  $("#allanScope").textContent = mode === "single" ? "只刷新第3章。" : "只刷新第2章。";
  $("#reloadFengine").textContent = mode === "single" ? "重新加载第2章" : "重新加载第1章";
  $("#reloadAllan").textContent = mode === "single" ? "重新加载第3章" : "重新加载第2章";
  state.page = 0;
  closeSidebarDrawer();
  if (render) refreshAll(false);
}

function clearContainer(id) {
  gpuManualTarget = null;
  gpuDesiredTarget = null;
  const node = $(`#${id}`);
  if (!node) return;
  node.querySelectorAll(".plot").forEach(plot => {
    gpuObserver.unobserve(plot);
    releaseGpuSlot(plot, false);
    gpuPlots.delete(plot);
  });
  node.replaceChildren();
}

function pageSubjects() {
  const subjects = state.mode === "single" ? state.adcs : state.pairs;
  const pages = Math.max(1, Math.ceil(subjects.length / PAGE_SIZE));
  state.page = Math.min(state.page, pages - 1);
  const shown = subjects.slice(state.page * PAGE_SIZE, (state.page + 1) * PAGE_SIZE);
  $("#pageStatus").textContent = `第 ${state.page + 1} / ${pages} 页；本页 ${shown.length} 个对象叠加在同一幅对应图中`;
  $("#previousPage").disabled = state.page === 0;
  $("#nextPage").disabled = state.page >= pages - 1;
  return shown;
}

function groupStatus(group, text, kind = "") {
  const node = $(`#${group}GroupStatus`);
  if (!node) return;
  node.className = `group-status ${kind}`.trim();
  node.textContent = text;
  const statuses = ["time", "fengine", "allan"].filter(name =>
    !(state.mode === "pair" && name === "time")).map(name => $(`#${name}GroupStatus`));
  if (statuses.some(item => item?.classList.contains("error"))) {
    $("#health").textContent = "有章节加载失败；其他章节仍可独立使用。";
  } else if (statuses.some(item => item?.classList.contains("loading"))) {
    $("#health").textContent = "正在读取权威数组；各章独立刷新。";
  } else {
    $("#health").textContent = `权威数据就绪 · 第 ${state.page + 1} 页 · ${state.bins.length} 个频率`;
  }
}

async function refreshGroup(group, resetPage = false) {
  try {
    readControls(resetPage);
    writeUrl();
    const shown = pageSubjects();
    const generation = ++renderGeneration[group];
    const guard = () => renderGeneration[group] === generation;
    groupStatus(group, "正在加载…", "loading");
    if (group === "time") {
      if (state.mode !== "single") return;
      clearContainer("singleTimeCards");
      await renderTimeSingle(shown, guard);
    } else if (group === "fengine") {
      clearContainer(state.mode === "single" ? "singleFengineCards" : "pairFengineCards");
      if (state.mode === "single") await renderFengineSingle(shown, guard);
      else await renderFenginePair(shown, guard);
    } else if (group === "allan") {
      clearContainer(state.mode === "single" ? "singleAllanCards" : "pairAllanCards");
      if (state.mode === "single") await renderAllanSingle(shown, guard);
      else await renderAllanPair(shown, guard);
    }
    if (!guard()) return;
    window.stage35RenderCounters[group] += 1;
    groupStatus(group, `已加载 · ${new Date().toLocaleTimeString("zh-CN", {hour12: false})}`);
  } catch (error) {
    groupStatus(group, `加载失败：${error.message}`, "error");
    console.error(error);
  }
}

async function refreshAll(resetPage = true) {
  readControls(resetPage);
  writeUrl();
  pageSubjects();
  const groups = state.mode === "single" ? ["time", "fengine", "allan"] : ["fengine", "allan"];
  await Promise.all(groups.map(group => refreshGroup(group, false)));
}

function scheduleRefresh(groups, resetPage = false, delay = 180) {
  groups.forEach(group => {
    clearTimeout(refreshTimers.get(group));
    refreshTimers.set(group, setTimeout(() => refreshGroup(group, resetPage), delay));
  });
}

function closeSidebarDrawer() {
  document.body.classList.remove("sidebar-opened");
  $("#sidebarBackdrop").hidden = true;
  $("#openSidebar").setAttribute("aria-expanded", "false");
}

function buildChoices(params) {
  const selectedAdcs = new Set((params.get("adcs") || "0").split(","));
  $("#adcChoices").innerHTML = `<legend>选择一个或多个 ADC</legend>${Array.from({length: 8}, (_, adc) =>
    `<label><input type="checkbox" name="adc" value="${adc}" ${selectedAdcs.has(String(adc)) ? "checked" : ""}>ADC${adc}</label>`).join("")}`;
  const selectedPairs = new Set((params.get("pairs") || "0-1").split(","));
  const pairs = [];
  for (let a = 0; a < 8; a += 1) for (let b = a + 1; b < 8; b += 1) pairs.push([a, b]);
  $("#pairChoices").innerHTML = `<legend class="sr-only">ADC 对</legend>${pairs.map(([a, b]) => {
    const value = `${a}-${b}`;
    return `<label><input type="checkbox" name="pair" value="${value}" ${selectedPairs.has(value) ? "checked" : ""}>ADC${a}–ADC${b}</label>`;
  }).join("")}`;
}

async function init() {
  const params = restoreUrl();
  requireWebGL();
  META = await api("/api/v2/meta");
  buildChoices(params);
  const comparison = META.stage35_comparison;
  if (comparison) {
    const t = comparison.time;
    const f = comparison.fengine;
    $("#stageComparison").textContent = `Stage 36 原始读数：TIME I/Q σ ${t.stage36_raw_range.map(x=>x.toFixed(2)).join("–")} count，F-engine 全频中位数 ${f.stage36_raw_range.map(x=>x.toFixed(2)).join("–")} count。消除数字增益后分别为 ${t.stage36_unified_range.map(x=>x.toFixed(2)).join("–")} 与 ${f.stage36_unified_range.map(x=>x.toFixed(2)).join("–")}；数值放大本身不代表科学性能改善。`;
  }
  $("#timeCapture").innerHTML = META.time_captures.map(x => `<option value="${x}">${x}</option>`).join("");
  $("#fftCapture").innerHTML = META.time_captures.map(x => `<option value="${x}">${x}</option>`).join("");
  const set = (id, key, fallback) => { const value = params.get(key) || fallback; $(`#${id}`).value = value; };
  set("frequencies", "bins", "124.843750MHz,128.593750MHz,140.000000MHz");
  set("timeCapture", "time_capture", params.get("time") || META.defaults.time_capture);
  set("timeShortBucket", "time_short", params.get("short") || "16");
  set("timeLongCadence", "time_long_ms", "100");
  set("timeStart", "time_start", "0");
  set("fengineShortBucket", "fengine_short", params.get("short") || "16");
  set("selfScan", "self_scan", params.get("scan") || "A");
  set("singleCadence", "self_ms", params.get("single_ms") || "100");
  set("fftCapture", "fft_capture", params.get("time") || META.defaults.time_capture);
  set("pairVisibilityCadence", "pair_visibility_ms", "100");
  set("allanScan", "allan_scan", params.get("scan") || "A");
  set("pairAllanCadence", "pair_allan_ms", params.get("pair_ms") || "100");
  set("allanForm", "allan_form", "variance");
  set("allanScale", "allan_scale", "relative");
  $("#identityText").textContent = JSON.stringify({
    频率范围_MHz: [META.rf_min_mhz, META.rf_max_mhz],
    频率间隔_MHz: META.channel_spacing_mhz,
    TIME_ONLY边界: META.limits.time,
    F_engine边界: META.limits.fengine,
    相关边界: META.limits.correlation,
    普通FFT边界: META.limits.fft,
    数据身份: META.identities,
    各数据段与数组身份: META.technical_sources,
  }, null, 2);
  $("#singleTab").onclick = () => setMode("single");
  $("#pairTab").onclick = () => setMode("pair");
  $("#reloadTime").onclick = () => refreshGroup("time");
  $("#reloadFengine").onclick = () => refreshGroup("fengine");
  $("#reloadAllan").onclick = () => refreshGroup("allan");
  $("#previousPage").onclick = async () => { state.page -= 1; writeUrl(); await refreshAll(false); scrollTo({top: 0, behavior: "smooth"}); };
  $("#nextPage").onclick = async () => { state.page += 1; writeUrl(); await refreshAll(false); scrollTo({top: 0, behavior: "smooth"}); };
  ["timeCapture", "timeShortBucket", "timeLongCadence"].forEach(id =>
    $(`#${id}`).addEventListener("change", () => scheduleRefresh(["time"])));
  $("#timeStart").addEventListener("input", () => scheduleRefresh(["time"], false, 350));
  ["fengineShortBucket", "selfScan", "singleCadence", "fftCapture", "pairVisibilityCadence"].forEach(id =>
    $(`#${id}`).addEventListener("change", () => scheduleRefresh(["fengine"])));
  ["allanScan", "pairAllanCadence", "allanForm", "allanScale"].forEach(id =>
    $(`#${id}`).addEventListener("change", () => scheduleRefresh(["allan"])));
  $("#frequencies").addEventListener("input", () => scheduleRefresh(["fengine", "allan"], false, 450));
  $("#adcChoices").addEventListener("change", () => refreshAll(true));
  $("#pairChoices").addEventListener("change", () => refreshAll(true));
  $("#collapseSidebar").onclick = () => document.body.classList.toggle("sidebar-collapsed");
  $("#openSidebar").onclick = () => {
    document.body.classList.add("sidebar-opened");
    $("#sidebarBackdrop").hidden = false;
    $("#openSidebar").setAttribute("aria-expanded", "true");
  };
  $("#closeSidebar").onclick = closeSidebarDrawer;
  $("#sidebarBackdrop").onclick = closeSidebarDrawer;
  setMode(state.mode, false);
  readControls(false);
  state.page = Math.max(0, Number(params.get("page") || 0));
  writeUrl();
  await refreshAll(false);
}

init().catch(error => {
  $("#health").textContent = `加载失败：${error.message}`;
  console.error(error);
});
