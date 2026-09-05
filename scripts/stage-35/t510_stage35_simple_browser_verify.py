#!/usr/bin/env python3
"""Verify the simplified Stage 35 application in a real offline browser."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def request(method: str, url: str, value: Any = None, timeout: float = 60) -> Any:
    data = None if value is None else json.dumps(value).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload) if payload else None


def webdriver(method: str, base: str, path: str, value: Any = None) -> Any:
    result = request(method, base + path, value, timeout=120)
    value = result.get("value") if isinstance(result, dict) else None
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(json.dumps(value, ensure_ascii=False))
    return value


def execute(base: str, session: str, script: str) -> Any:
    return webdriver("POST", base, f"/session/{session}/execute/sync",
                     {"script": script, "args": []})


def wait_http(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request("GET", url, timeout=2)
            return
        except Exception:
            time.sleep(.2)
    raise TimeoutError(f"server did not become ready: {url}")


def wait_ready(driver: str, session: str, wanted: str, timeout: float = 240) -> str:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        last = execute(driver, session, "return document.getElementById('health').textContent")
        if wanted in last:
            return last
        if "无法显示" in last or "加载失败" in last:
            raise RuntimeError(last)
        time.sleep(.5)
    raise TimeoutError(f"browser did not reach {wanted!r}: {last}")


def wait_counters(base: str, session: str, expected: dict[str, int], timeout: float = 240) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    last: dict[str, int] = {}
    while time.monotonic() < deadline:
        last = execute(base, session, "return window.stage35RenderCounters")
        if all(int(last.get(key, -1)) >= value for key, value in expected.items()):
            return last
        time.sleep(.2)
    raise TimeoutError(f"render counters did not reach {expected}: {last}")


def activate_plot(driver: str, session: str, selector: str, index: int = 0) -> dict[str, Any]:
    encoded = json.dumps(selector)
    execute(driver, session, f"""
      const p=document.querySelectorAll({encoded})[{index}];
      if(!p) throw new Error('missing GPU plot');
      p.scrollIntoView({{block:'center',behavior:'instant'}});
      p.querySelector('.gpu-placeholder')?.click();
      return true;
    """)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        result = execute(driver, session, f"""
          const p=document.querySelectorAll({encoded})[{index}];
          const g=p?.querySelector('.js-plotly-plot');
          return {{state:p?.dataset.gpuState||'', renderer:p?.dataset.gpuRenderer||'',
            types:(g?.data||[]).map(t=>t.type), names:(g?.data||[]).map(t=>t.name||''),
            uids:(g?.data||[]).map(t=>t.uid||''),
            markerStyles:(g?.data||[]).filter(t=>t.visible!==false && (t.mode||'').includes('markers'))
              .map(t=>({{name:t.name||'',symbol:t.marker?.symbol||''}})),
            badMarkerSymbols:(g?.data||[]).filter(t=>t.visible!==false && (t.mode||'').includes('markers') && !['x','triangle-up-open'].includes(t.marker?.symbol)).map(t=>t.marker?.symbol||''),
            axes:[g?._fullLayout?.xaxis?.title?.text||'',g?._fullLayout?.yaxis?.title?.text||''],
            layoutHeight:g?._fullLayout?.height||0,
            targetHeight:p?.getBoundingClientRect().height||0,
            clippedTimeAxis:g ? [...g.querySelectorAll('.xtitle,.xaxislayer-above .xtick text')].some(x=>
              x.getBoundingClientRect().bottom > p.getBoundingClientRect().bottom+1 ||
              x.getBoundingClientRect().top < p.getBoundingClientRect().top-1) : true,
            surface:g?.id||'', surfaces:document.querySelectorAll('.gpu-shared-surface').length,
            text:p?.textContent||'',
            active:document.querySelectorAll('[data-gpu-state=rendered],[data-gpu-state=rendering]').length}};
        """)
        if result["state"] == "error":
            raise RuntimeError(f"GPU plot {index} entered error state: {result}")
        if result["state"] == "rendered":
            return result
        time.sleep(.2)
    raise TimeoutError(f"GPU plot {index} did not render: {result}")


def verify_gpu_plots(driver: str, session: str, selector: str) -> dict[str, Any]:
    count = execute(
        driver, session, f"return document.querySelectorAll({json.dumps(selector)}).length"
    )
    rows = [activate_plot(driver, session, selector, index) for index in range(count)]
    bad = [row for row in rows if row["renderer"] != "scattergl" or
           not row["types"] or any(kind != "scattergl" for kind in row["types"]) or
           len(row["uids"]) != 64 or len(set(row["uids"])) != 64 or
           row["badMarkerSymbols"] or
           row["clippedTimeAxis"] or abs(row["layoutHeight"] - row["targetHeight"]) > 1 or
           "WebGL is not supported" in row["text"] or
           row["surface"] != "stage35-shared-gpu-surface" or row["surfaces"] != 1 or
           row["active"] > 1]
    if bad:
        raise RuntimeError(f"GPU-only/context-budget contract failed: {bad}")
    return {
        "declared_plots": count,
        "max_active_plots": max(row["active"] for row in rows),
        "headless_webgl_warning_plots": sum(
            "WebGL is not supported" in row["text"] for row in rows
        ),
        "trace_names": [name for row in rows for name in row["names"]],
        "axis_titles": [title for row in rows for title in row["axes"] if title],
        "shared_surface_ids": sorted({row["surface"] for row in rows}),
        "fixed_trace_slots": sorted({len(row["uids"]) for row in rows}),
    }


def verify_layout(driver: str, session: str, label: str) -> dict[str, Any]:
    result = execute(driver, session, """
      const visible = element => {
        const r=element.getBoundingClientRect();
        return r.width>0 && r.height>0;
      };
      const contained=[];
      for(const element of document.querySelectorAll('.subject-source,.explanation,.formula-box')) {
        if(!visible(element)) continue;
        const card=element.closest('.subject-card');
        const a=element.getBoundingClientRect(), b=card.getBoundingClientRect();
        if(a.left < b.left-1 || a.right > b.right+1) contained.push({
          className:element.className,left:a.left,right:a.right,cardLeft:b.left,cardRight:b.right
        });
      }
      const plotTitles=[...document.querySelectorAll('.gtitle')]
        .filter(visible).map(x=>x.textContent.trim()).filter(Boolean);
      const formulaBoxes=[...document.querySelectorAll('.formula-box')].filter(visible);
      return {
        viewport:document.documentElement.clientWidth,
        documentWidth:document.documentElement.scrollWidth,
        horizontalOverflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+1,
        escapedElements:contained,
        emptyFormulaBoxes:formulaBoxes.filter(x=>!x.querySelector('.formula-line')).length,
        plotTitles
      };
    """)
    if (result["horizontalOverflow"] or result["escapedElements"] or
            result["emptyFormulaBoxes"] or result["plotTitles"]):
        raise RuntimeError(f"{label} responsive layout failed: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--static-root", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--app-port", type=int, default=8036)
    parser.add_argument("--driver-port", type=int, default=9518)
    parser.add_argument("--window-width", type=int, default=1720)
    parser.add_argument("--headless-webgl-structural-only", action="store_true")
    parser.add_argument("--headful-hardware", action="store_true")
    args = parser.parse_args()
    if args.headless_webgl_structural_only and args.headful_hardware:
        parser.error("--headless-webgl-structural-only and --headful-hardware are mutually exclusive")
    app_base = f"http://127.0.0.1:{args.app_port}"
    driver_base = f"http://127.0.0.1:{args.driver_port}"
    app = subprocess.Popen([
        str(args.python), str(args.server), "--config", str(args.config),
        "--helper-dir", str(args.helper_dir), "--static-root", str(args.static_root),
        "--bind", f"127.0.0.1:{args.app_port}",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    driver = subprocess.Popen([str(args.chromedriver), f"--port={args.driver_port}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session = None
    evidence: dict[str, Any] = {
        "format": "T510_STAGE35_SIMPLE_BROWSER_VERIFY_V1", "status": "FAIL", "errors": []
    }
    try:
        wait_http(app_base + "/healthz")
        wait_http(driver_base + "/status")
        chrome_args = [f"--window-size={args.window_width},1200"]
        if not args.headful_hardware:
            chrome_args.extend([
                "--headless=new", "--no-sandbox", "--enable-unsafe-swiftshader",
                "--use-gl=angle", "--use-angle=swiftshader",
            ])
        session = webdriver("POST", driver_base, "/session", {"capabilities": {"alwaysMatch": {
            "browserName": "chrome", "pageLoadStrategy": "normal",
            "goog:loggingPrefs": {"browser": "ALL", "performance": "ALL"},
            "goog:chromeOptions": {"binary": str(args.chrome), "args": chrome_args},
        }}})["sessionId"]
        # Deliberately use the prior URL vocabulary. The application must migrate it
        # to the explicit per-chapter parameter names without losing the selection.
        url = (app_base + "/?mode=single&adcs=0,1&pairs=0-1,2-3&"
               "bins=124.843750MHz,128.593750MHz,140.000000MHz&time=A-pre&"
               "short=16&scan=A&single_ms=100&pair_ms=100&allan_form=variance&allan_scale=relative")
        webdriver("POST", driver_base, f"/session/{session}/url", {"url": url})
        wait_ready(driver_base, session, "权威数据就绪")
        migrated_url = webdriver("GET", driver_base, f"/session/{session}/url")
        migrated_params = urllib.parse.parse_qs(urllib.parse.urlsplit(migrated_url).query)
        if (migrated_params.get("time_capture") != ["A-pre"] or
                migrated_params.get("fengine_short") != ["16"] or
                migrated_params.get("self_scan") != ["A"] or
                migrated_params.get("pair_allan_ms") != ["100"] or
                any(old in migrated_params for old in ("time", "short", "scan", "single_ms", "pair_ms"))):
            raise RuntimeError(f"legacy URL was not migrated to scoped controls: {migrated_url}")
        shell = execute(driver_base, session, """
          return {sidebar:!!document.getElementById('sidebar'),
            headerControls:document.querySelectorAll('.page-header input,.page-header select,.page-header button').length,
            timeVisible:!document.getElementById('timeControls').hidden,
            groups:[...document.querySelectorAll('.sidebar .chapter-controls')].map(x=>x.dataset.group)};
        """)
        if not shell["sidebar"] or shell["headerControls"] or not shell["timeVisible"] or shell["groups"] != ["time", "fengine", "allan"]:
            raise RuntimeError(f"sidebar/top-control contract failed: {shell}")
        single_gpu = verify_gpu_plots(driver_base, session, "#singleView .plot")
        activate_plot(driver_base, session, "#singleTimeCards .plot", 0)
        interaction_before = execute(driver_base, session, """
          const target=document.querySelectorAll('#singleTimeCards .plot')[0];
          const plot=target.querySelector('.js-plotly-plot');
          const button=target.closest('.figure').querySelector('.step-toggle');
          const measured=(plot.data||[]).filter(t=>t.visible!==false && (t.x||[]).length);
          return {
            dragmode:plot._fullLayout.dragmode,
            removedTools:plot._context.modeBarButtonsToRemove||[],
            names:measured.map(t=>t.name||''),
            symbols:measured.filter(t=>(t.mode||'').includes('markers')).map(t=>t.marker?.symbol||''),
            modes:measured.map(t=>t.mode),
            stepHidden:button.hidden,
            stepPressed:button.getAttribute('aria-pressed'),
            stepText:button.textContent
          };
        """)
        if (interaction_before["dragmode"] != "pan" or interaction_before["removedTools"] or
                interaction_before["stepHidden"] or
                interaction_before["stepPressed"] != "false" or
                set(interaction_before["symbols"]) != {"x", "triangle-up-open"} or
                any(value != "markers" for value in interaction_before["modes"])):
            raise RuntimeError(f"default pan/IQ-marker contract failed: {interaction_before}")
        interaction_enabled = execute(driver_base, session, """
          const target=document.querySelectorAll('#singleTimeCards .plot')[0];
          target.closest('.figure').querySelector('.step-toggle').click();
          const plot=target.querySelector('.js-plotly-plot');
          const measured=(plot.data||[]).filter(t=>t.visible!==false && (t.x||[]).length);
          return {modes:measured.map(t=>t.mode), shapes:measured.map(t=>t.line?.shape||''),
            lineColors:measured.map(t=>t.line?.color||''), lineWidths:measured.map(t=>t.line?.width||0),
            pressed:target.closest('.figure').querySelector('.step-toggle').getAttribute('aria-pressed')};
        """)
        if (interaction_enabled["pressed"] != "true" or
                any(value != "lines+markers" for value in interaction_enabled["modes"]) or
                any(value != "hv" for value in interaction_enabled["shapes"]) or
                any(not value.startswith("rgba(") or not value.endswith(", 0.24)")
                    for value in interaction_enabled["lineColors"]) or
                any(abs(value - 0.8) > 1e-9 for value in interaction_enabled["lineWidths"])):
            raise RuntimeError(f"step-line enable contract failed: {interaction_enabled}")
        activate_plot(driver_base, session, "#singleTimeCards .plot", 1)
        interaction_other = execute(driver_base, session, """
          const target=document.querySelectorAll('#singleTimeCards .plot')[1];
          const plot=target.querySelector('.js-plotly-plot');
          return (plot.data||[]).filter(t=>t.visible!==false && (t.x||[]).length).map(t=>t.mode);
        """)
        if any(value != "markers" for value in interaction_other):
            raise RuntimeError(f"step state leaked into another plot: {interaction_other}")
        activate_plot(driver_base, session, "#singleTimeCards .plot", 0)
        interaction_restored = execute(driver_base, session, """
          const target=document.querySelectorAll('#singleTimeCards .plot')[0];
          const plot=target.querySelector('.js-plotly-plot');
          return {modes:(plot.data||[]).filter(t=>t.visible!==false && (t.x||[]).length).map(t=>t.mode),
            pressed:target.closest('.figure').querySelector('.step-toggle').getAttribute('aria-pressed')};
        """)
        if (interaction_restored["pressed"] != "true" or
                any(value != "lines+markers" for value in interaction_restored["modes"])):
            raise RuntimeError(f"step state was not restored with its plot: {interaction_restored}")
        activate_plot(driver_base, session, "#singleAllanCards .plot", 0)
        single = execute(driver_base, session, """
          const plots=Array.from(document.querySelectorAll('#singleView .js-plotly-plot'));
          const figures=Array.from(document.querySelectorAll('#singleView .figure'));
          const allanNames=(document.querySelector('#singleAllanCards .js-plotly-plot')?.data||[])
            .filter(t=>t.visible!==false && (t.x||[]).length).map(t=>t.name||'');
          return {plots:figures.length,cards:[...document.querySelectorAll('#singleView .subject-card')].length,
            timeCards:document.querySelectorAll('#singleTimeCards .subject-card').length,
            fCards:document.querySelectorAll('#singleFengineCards .subject-card').length,
            allanCards:document.querySelectorAll('#singleAllanCards .subject-card').length,
            groupCounts:[...document.querySelectorAll('#singleView .subject-card')].map(x=>x.dataset.subjectCount),
            allanNames,
            notes:figures.map(f=>({terms:f.querySelectorAll('.explanation dt').length,
              formula:!!f.querySelector('.formula-box .katex'),number:/[0-9]/.test(f.querySelector('.calculated').textContent)})),
            axes:[...document.querySelectorAll('#singleView .xtitle,#singleView .ytitle')].map(x=>x.textContent),
            white:plots.some(p=>(p.data||[]).some(t=>(t.name||'').includes('如果是白噪声，应按此速度下降')))};
        """)
        if single["timeCards"] != 1 or single["fCards"] != 1 or single["allanCards"] != 1:
            raise RuntimeError(f"multi-ADC grouped-card contract failed: {single}")
        if (single["groupCounts"] != ["2", "2", "2"] or
                not all(any(adc in name for name in interaction_before["names"]) for adc in ("ADC0", "ADC1")) or
                not all(any(adc in name for name in single["allanNames"]) for adc in ("ADC0", "ADC1"))):
            raise RuntimeError(f"multi-ADC same-plot overlay failed: {single}")
        if single["plots"] != 10 or any(row["terms"] != 5 or not row["formula"] or not row["number"] for row in single["notes"]):
            raise RuntimeError(f"single-ADC plot/note contract failed: {single}")
        if not single["white"] or not any("ADU" in value for value in single_gpu["axis_titles"]):
            raise RuntimeError(f"single-ADC axis/white-reference contract failed: {single}")
        allan_click = execute(driver_base, session, """
          const p=document.querySelector('#singleAllanCards .js-plotly-plot');
          const before=p.closest('.figure').querySelector('.calculated').textContent;
          p.emit('plotly_click',{points:[{customdata:p.data[0].customdata[1]}]});
          const after=p.closest('.figure').querySelector('.calculated').textContent;
          return {changed:before!==after,text:after};
        """)
        if not allan_click["changed"] or not all(token in allan_click["text"] for token in ("N=", "m=", "K=", "平方差之和")):
            raise RuntimeError(f"Allan point explanation did not update: {allan_click}")

        initial_counters = execute(driver_base, session, "return {...window.stage35RenderCounters}")
        execute(driver_base, session, """
          const x=document.getElementById('timeLongCadence');x.value='1000';
          x.dispatchEvent(new Event('change',{bubbles:true}));return true;
        """)
        after_time = wait_counters(driver_base, session, {"time": initial_counters["time"] + 1})
        if after_time["fengine"] != initial_counters["fengine"] or after_time["allan"] != initial_counters["allan"]:
            raise RuntimeError(f"TIME cadence refreshed another chapter: {initial_counters} -> {after_time}")
        execute(driver_base, session, """
          const x=document.getElementById('singleCadence');x.value='1000';
          x.dispatchEvent(new Event('change',{bubbles:true}));return true;
        """)
        after_fengine = wait_counters(driver_base, session, {"fengine": after_time["fengine"] + 1})
        if after_fengine["time"] != after_time["time"] or after_fengine["allan"] != after_time["allan"]:
            raise RuntimeError(f"F-engine cadence refreshed another chapter: {after_time} -> {after_fengine}")
        execute(driver_base, session, "document.getElementById('reloadAllan').click();return true")
        after_allan = wait_counters(driver_base, session, {"allan": after_fengine["allan"] + 1})
        if after_allan["time"] != after_fengine["time"] or after_allan["fengine"] != after_fengine["fengine"]:
            raise RuntimeError(f"Allan manual reload refreshed another chapter: {after_fengine} -> {after_allan}")

        execute(driver_base, session, "document.getElementById('pairTab').click();return true")
        wait_ready(driver_base, session, "权威数据就绪")
        pair_gpu = verify_gpu_plots(driver_base, session, "#pairView .plot")
        pair_visibility_overlay = activate_plot(driver_base, session, "#pairFengineCards .plot", 0)
        pair_allan_overlay = activate_plot(driver_base, session, "#pairAllanCards .plot", 0)
        pair = execute(driver_base, session, """
          const figures=Array.from(document.querySelectorAll('#pairView .figure'));
          const allanNames=(document.querySelector('#pairAllanCards .js-plotly-plot')?.data||[])
            .filter(t=>t.visible!==false && (t.x||[]).length).map(t=>t.name||'');
          return {plots:figures.length,timeCards:document.querySelectorAll('#pairTimeCards .subject-card').length,
            fCards:document.querySelectorAll('#pairFengineCards .subject-card').length,
            allanCards:document.querySelectorAll('#pairAllanCards .subject-card').length,
            groupCounts:[...document.querySelectorAll('#pairView .subject-card')].map(x=>x.dataset.subjectCount),
            allanNames,
            selectedLong:[...document.querySelectorAll('#pairFengineCards .figure h4')]
              .filter(x=>x.textContent.includes('900 秒 F-engine 复可见度')).map(x=>x.textContent),
            forbiddenPairTime:document.getElementById('pairView').textContent.includes('TIME_ONLY 每个样点的瞬时复乘'),
            forbiddenPairFft:document.getElementById('pairView').textContent.includes('Hann FFT 的相关参照'),
            formulas:[...document.querySelectorAll('#pairView .formula-box')].every(x=>!!x.querySelector('.katex'))};
        """)
        if pair["timeCards"] != 0 or pair["fCards"] != 1 or pair["allanCards"] != 1 or pair["plots"] != 4:
            raise RuntimeError(f"multi-pair grouped-card contract failed: {pair}")
        if (pair["groupCounts"] != ["2", "2"] or
                not all(any(name in trace for trace in pair_visibility_overlay["names"]) for name in ("ADC0–ADC1", "ADC2–ADC3")) or
                not all(any(name in trace for trace in pair_allan_overlay["names"]) for name in ("ADC0–ADC1", "ADC2–ADC3"))):
            raise RuntimeError(f"multi-pair same-plot overlay failed: {pair}")
        pair_markers = pair_visibility_overlay["markerStyles"]
        if (not pair_markers or
                any(row["symbol"] != "x" for row in pair_markers if "幅度" in row["name"]) or
                any(row["symbol"] != "triangle-up-open" for row in pair_markers if "相位" in row["name"])):
            raise RuntimeError(f"amplitude/phase marker pairing failed: {pair_markers}")
        pair["gray"] = any("弱相关相位" in name for name in pair_gpu["trace_names"])
        if (not pair["gray"] or len(pair["selectedLong"]) != 1 or
                pair["forbiddenPairTime"] or pair["forbiddenPairFft"] or not pair["formulas"]):
            raise RuntimeError(f"pair visibility contract failed: {pair}")
        pair_layout = verify_layout(driver_base, session, "pair")
        webdriver("POST", driver_base, f"/session/{session}/window/rect",
                  {"width": 640, "height": 1000})
        time.sleep(.35)
        mobile_closed = execute(driver_base, session, """
          return {openVisible:getComputedStyle(document.getElementById('openSidebar')).display!=='none',
            sidebarLeft:document.getElementById('sidebar').getBoundingClientRect().left,
            overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+1};
        """)
        execute(driver_base, session, "document.getElementById('openSidebar').click();return true")
        time.sleep(.35)
        mobile_open = execute(driver_base, session, """
          return {opened:document.body.classList.contains('sidebar-opened'),
            sidebarLeft:document.getElementById('sidebar').getBoundingClientRect().left,
            expanded:document.getElementById('openSidebar').getAttribute('aria-expanded')};
        """)
        if (not mobile_closed["openVisible"] or mobile_closed["sidebarLeft"] >= 0 or
                mobile_closed["overflow"] or not mobile_open["opened"] or
                abs(mobile_open["sidebarLeft"]) > 1 or mobile_open["expanded"] != "true"):
            raise RuntimeError(f"mobile sidebar drawer failed: closed={mobile_closed}, open={mobile_open}")
        execute(driver_base, session, "document.getElementById('closeSidebar').click();return true")
        webdriver("POST", driver_base, f"/session/{session}/window/rect",
                  {"width": args.window_width, "height": 1200})

        text = execute(driver_base, session, "return document.documentElement.textContent")
        source = execute(driver_base, session, "return document.documentElement.outerHTML")
        canonical_assets = ("/static/stage35-app.css", "/static/stage35-plotly-strict.min.js",
                            "/static/stage35-app.js")
        if any(item not in source for item in canonical_assets) or "?v=" in source:
            raise RuntimeError("page is not using the fixed, versionless Stage 35 asset names")
        if "sha256-yocV5+NI4dVvtdMVdceFC1zdJ39gG/BHwP78QXLilXs=" not in source:
            raise RuntimeError("Plotly strict bundle is not protected by its frozen SHA-256 identity")
        if "CSS_SRI_PLACEHOLDER" in source:
            raise RuntimeError("Stage 35 stylesheet still contains an unresolved SHA-256 placeholder")
        if "integrity=\"sha256-" not in source:
            raise RuntimeError("Stage 35 stylesheet is not protected by its frozen SHA-256 identity")
        required = ["这些点是什么", "这个数字从哪里来", "怎么算", "当前算得什么", "怎样理解",
                    "瞬时复乘", "复可见度 Allan 方差", "不可作天文相位解释"]
        missing = [item for item in required if item not in text]
        forbidden = [item for item in ("ADEV", "Click to enter axis title", "功率谱密度",
                                        "温度回归", "谱峰度", "动态谱") if item in text or item in source]
        if missing or forbidden:
            raise RuntimeError(f"human text contract failed: missing={missing}, forbidden={forbidden}")
        narrative = execute(driver_base, session, """
          const copy=document.querySelector('main').cloneNode(true);
          copy.querySelector('.identity')?.remove();
          return copy.textContent;
        """)
        identity = execute(driver_base, session, "return document.querySelector('.identity').textContent")
        if ("iq16_npy" in narrative or "SHA-256" in narrative or
                "iq16_npy" not in identity or "e11e2de8d0ab94bf2f0c075f2c514c9c603abe1842ecb7d02ab27ac3c37bf5e2" not in identity):
            raise RuntimeError("storage identity was not confined to the folded technical section")

        meta = request("GET", app_base + "/api/v2/meta")
        if meta["rf_min_mhz"] != 40.0 or meta["rf_max_mhz"] != 359.921875:
            raise RuntimeError(f"RF range mismatch: {meta['rf_min_mhz']}, {meta['rf_max_mhz']}")
        raw = request("GET", app_base + "/api/v2/timeseries?domain=fengine_raw_single&adc=0&bins=3182&bucket=1")
        if raw["calculation"]["source_frames"] != 4096 or len(raw["series"][0]["power"]) != 4096:
            raise RuntimeError("the raw F-engine view is not backed by 4096 complete spectra")
        raw_time = request("GET", app_base + "/api/v2/timeseries?domain=time_single&adc=0&capture=A-post&bucket=raw&start_sample=700")
        averaged_time = request("GET", app_base + "/api/v2/timeseries?domain=time_single&adc=0&capture=A-post&bucket=4")
        time_long = {cadence: request("GET", app_base + f"/api/v2/timeseries?domain=time_long_single&adc=0&cadence_ms={cadence}")
                     for cadence in (10, 100, 1000)}
        if (not all(isinstance(value, int) for value in raw_time["i_adu"] + raw_time["q_adu"]) or
                not all(isinstance(value, int) for value in raw["series"][0]["i"] + raw["series"][0]["q"])):
            raise RuntimeError("unaveraged IQ values were not serialized as integers")
        if not any(isinstance(value, float) and not value.is_integer()
                   for value in averaged_time["i_adu"] + averaged_time["q_adu"]):
            raise RuntimeError("averaged TIME IQ did not preserve fractional means")
        if ("不是 ADC 在 3.84 GS/s 下的原始转换码" not in raw_time["source"]["meaning"] or
                "technical_sources" not in meta):
            raise RuntimeError("human source meaning or folded technical identity is missing")
        if ([len(time_long[x]["time_s"]) for x in (10, 100, 1000)] != [90000, 9000, 900] or
                any("没有保存约9.2 TB原始流" not in time_long[x]["source"]["meaning"] for x in time_long)):
            raise RuntimeError("TIME_ONLY 900 s cadence/source contract failed")
        import numpy as np
        base_values = np.column_stack([time_long[10]["mean_i_adu"], time_long[10]["mean_q_adu"],
                                       time_long[10]["mean_power_adu2"]])
        base_weights = np.asarray(time_long[10]["n_valid"], dtype=np.float64)
        for cadence, width in ((100, 10), (1000, 100)):
            groups = len(base_values) // width
            weights = base_weights[:groups * width].reshape(groups, width)
            expected = np.sum(base_values[:groups * width].reshape(groups, width, 3) * weights[..., None], axis=1) / np.sum(weights, axis=1)[:, None]
            actual = np.column_stack([time_long[cadence]["mean_i_adu"], time_long[cadence]["mean_q_adu"], time_long[cadence]["mean_power_adu2"]])
            if not np.allclose(expected, actual, rtol=2e-15, atol=2e-15):
                raise RuntimeError(f"TIME_ONLY {cadence} ms is not the weighted merge of 10 ms data")
        for cadence, expected in ((100, 9000), (1000, 900)):
            result = request("GET", app_base + f"/api/v2/timeseries?domain=fengine_long_pair&pair=0-1&bins=3182&cadence_ms={cadence}")
            if len(result["time_s"]) != expected or not all(int(v) > 0 for v in result["series"][0]["n_valid"]):
                raise RuntimeError(f"pair cadence {cadence} ms contract failed")
        try:
            request("GET", app_base + "/api/v2/timeseries?domain=fengine_raw_single&adc=9&bins=3182&bucket=1")
            raise RuntimeError("invalid ADC unexpectedly succeeded")
        except urllib.error.HTTPError as error:
            if error.code != 400:
                raise
        try:
            request("GET", app_base + "/api/v2/allan?subject=single&adc=0&bins=1,2,3,4,5")
            raise RuntimeError("more than four frequencies unexpectedly succeeded")
        except urllib.error.HTTPError as error:
            if error.code != 400:
                raise
        try:
            request("POST", app_base + "/api/v2/meta", {})
            raise RuntimeError("read-only application unexpectedly accepted POST")
        except urllib.error.HTTPError as error:
            if error.code != 405:
                raise
        try:
            request("GET", app_base + "/static/../app_config.json")
            raise RuntimeError("static path traversal unexpectedly succeeded")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise

        # Five selected ADCs: each page has one grouped card; its subject count is four then one.
        execute(driver_base, session, "document.getElementById('singleTab').click();return true")
        wait_ready(driver_base, session, "权威数据就绪")
        execute(driver_base, session, """
          document.querySelectorAll('input[name=adc]').forEach(x=>x.checked=Number(x.value)<5);
          document.querySelector('input[name=adc]').dispatchEvent(new Event('change',{bubbles:true}));return true;
        """)
        wait_ready(driver_base, session, "权威数据就绪")
        page_one = execute(driver_base, session, """
          const cards=document.querySelectorAll('#singleTimeCards .subject-card');
          return {cards:cards.length,subjects:Number(cards[0]?.dataset.subjectCount||0)};
        """)
        if page_one != {"cards": 1, "subjects": 4}:
            raise RuntimeError(f"first lazy page grouping is {page_one}, expected one card with four objects")
        single_layout = verify_layout(driver_base, session, "single")
        execute(driver_base, session, "document.getElementById('nextPage').click();return true")
        wait_ready(driver_base, session, "权威数据就绪")
        page_two = execute(driver_base, session, """
          const cards=document.querySelectorAll('#singleTimeCards .subject-card');
          return {cards:cards.length,subjects:Number(cards[0]?.dataset.subjectCount||0)};
        """)
        if page_two != {"cards": 1, "subjects": 1}:
            raise RuntimeError(f"second lazy page grouping is {page_two}, expected one card with one object")
        gpu_debug = execute(driver_base, session, "return window.stage35GpuDebug")
        if (gpu_debug.get("plotlyVersion") != "3.7.0" or
                gpu_debug.get("plotlyBundle") != "strict-csp" or
                gpu_debug.get("newPlotCalls") != 1 or
                gpu_debug.get("fixedTraceSlots") != 64 or
                gpu_debug.get("fatal")):
            raise RuntimeError(f"single persistent Plotly graph contract failed: {gpu_debug}")
        current_url = webdriver("GET", driver_base, f"/session/{session}/url")
        if "page=1" not in current_url or "adcs=0%2C1%2C2%2C3%2C4" not in current_url:
            raise RuntimeError(f"selection state was not written to URL: {current_url}")

        logs = webdriver("POST", driver_base, f"/session/{session}/log", {"type": "performance"})
        urls = []
        for row in logs:
            message = json.loads(row["message"])["message"]
            if message["method"] == "Network.requestWillBeSent":
                urls.append(message["params"]["request"]["url"])
        external = sorted({item for item in urls if not item.startswith(app_base) and not item.startswith("data:")})
        if external:
            raise RuntimeError(f"browser made external requests: {external}")
        console = webdriver("POST", driver_base, f"/session/{session}/log", {"type": "browser"})
        severe = [row for row in console if row.get("level") == "SEVERE"]
        if severe:
            raise RuntimeError(f"severe browser console errors: {severe}")
        activate_plot(driver_base, session, "#singleAllanCards .plot", 0)
        time.sleep(.5)
        encoded = webdriver("GET", driver_base, f"/session/{session}/screenshot")
        args.screenshot.write_bytes(base64.b64decode(encoded))
        evidence.update({
            "status": "PASS", "url": url, "url_after_pagination": current_url,
            "single": single, "single_gpu": single_gpu, "allan_click": allan_click,
            "interaction": {"before": interaction_before, "enabled": interaction_enabled,
                            "other_plot": interaction_other, "restored": interaction_restored},
            "pair": pair, "pair_gpu": pair_gpu,
            "pair_layout": pair_layout, "single_layout": single_layout,
            "scoped_refresh_counters": {"initial": initial_counters, "time": after_time,
                                        "fengine": after_fengine, "allan": after_allan},
            "mobile_sidebar": {"closed": mobile_closed, "open": mobile_open},
            "headless_webgl_structural_only": args.headless_webgl_structural_only,
            "headful_hardware": args.headful_hardware,
            "gpu_debug": gpu_debug,
            "pagination": {"first_page_objects": page_one, "second_page_objects": page_two},
            "raw_fengine_spectra": raw["calculation"]["source_frames"],
            "raw_iq_json_types": {"time": "integer", "fengine": "integer",
                                  "averaged_time": "fractional"},
            "network_request_count": len(urls), "external_network_requests": external,
            "severe_console_errors": severe,
        })
    except Exception as error:
        evidence["errors"].append(f"{type(error).__name__}: {error}")
        raise
    finally:
        if session:
            if evidence.get("status") != "PASS":
                try:
                    evidence["failure_console"] = webdriver(
                        "POST", driver_base, f"/session/{session}/log", {"type": "browser"}
                    )
                except Exception as log_error:
                    evidence["failure_console_error"] = str(log_error)
                try:
                    encoded = webdriver("GET", driver_base, f"/session/{session}/screenshot")
                    args.screenshot.write_bytes(base64.b64decode(encoded))
                except Exception as screenshot_error:
                    evidence["failure_screenshot_error"] = str(screenshot_error)
            try:
                webdriver("DELETE", driver_base, f"/session/{session}")
            except Exception:
                pass
        driver.terminate()
        app.terminate()
        try:
            driver.wait(timeout=5)
        except subprocess.TimeoutExpired:
            driver.kill()
        try:
            app.wait(timeout=10)
        except subprocess.TimeoutExpired:
            app.kill()
        if app.stderr:
            evidence["server_stderr"] = app.stderr.read()[-12000:]
        args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
