#!/usr/bin/env python3
"""Build the Stage 35 S2 single-file, offline scientific HTML report.

The Parquet/Zarr archive remains authoritative.  The report embeds an exact
CSV rendering of every metrics_by_scan row and compact presentation arrays for
interactive plots.  No network resource, CDN, external CSS, JS, or image is
referenced by the generated HTML.
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ADC_COUNT = 8
BIN_COUNT = 4096
BLOCK_COUNT = 16
BLOCK_BINS = 256
SCAN_LABELS = ("A", "B", "C")
TAU_SECONDS = (2.0, 4.0, 15.0, 30.0)
QUICK_FIELDS = (
    "mean_power_count2",
    "power_density_count2_per_hz",
    "native_std_power_count2",
    "integration_std_2s",
    "integration_std_4s",
    "integration_std_15s",
    "integration_std_30s",
    "sigma_over_theory_2s",
    "sigma_over_theory_4s",
    "sigma_over_theory_15s",
    "sigma_over_theory_30s",
    "spectral_kurtosis",
    "temperature_r2",
    "between_scan_fractional_std",
)
METRIC_LIST_COLUMNS = {
    "integration_mean_count2": ("2s", "4s", "15s", "30s"),
    "integration_std_count2": ("2s", "4s", "15s", "30s"),
    "integration_mad_count2": ("2s", "4s", "15s", "30s"),
    "integration_mean_ci_low_count2": ("2s", "4s", "15s", "30s"),
    "integration_mean_ci_high_count2": ("2s", "4s", "15s", "30s"),
    "sigma_theory_enbw_count2": ("2s", "4s", "15s", "30s"),
    "sigma_pfb_model_count2": ("2s", "4s", "15s", "30s"),
    "sigma_short_cov_count2": ("2s", "4s", "15s", "30s"),
    "sigma_over_theory": ("2s", "4s", "15s", "30s"),
    "sigma_over_pfb_model": ("2s", "4s", "15s", "30s"),
    "local_sigma_log_slopes": ("2_to_4s", "4_to_15s", "15_to_30s"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parquet_path(root: Path, family: str, scan: str, block: int) -> Path:
    return root / family / f"scan={scan}" / f"block={block:02d}" / "part.parquet"


def ordered_metric_table(root: Path, scan: str, block: int) -> pa.Table:
    table = pq.read_table(parquet_path(root, "metrics_by_scan", scan, block))
    adc = table["adc_id"].to_numpy(zero_copy_only=False)
    bins = table["global_bin"].to_numpy(zero_copy_only=False)
    order = np.lexsort((bins, adc))
    if not np.array_equal(order, np.arange(table.num_rows)):
        table = table.take(pa.array(order))
    expected_adc = np.repeat(np.arange(ADC_COUNT), BLOCK_BINS)
    expected_bin = np.tile(np.arange(block * BLOCK_BINS, (block + 1) * BLOCK_BINS), ADC_COUNT)
    if not np.array_equal(table["adc_id"].to_numpy(), expected_adc):
        raise RuntimeError(f"{scan}/block{block:02d}: ADC row identity mismatch")
    if not np.array_equal(table["global_bin"].to_numpy(), expected_bin):
        raise RuntimeError(f"{scan}/block{block:02d}: bin row identity mismatch")
    return table


def ordered_temporal_table(root: Path, scan: str, block: int) -> pa.Table:
    table = pq.read_table(parquet_path(root, "temporal_metrics", scan, block))
    adc = table["adc_id"].to_numpy(zero_copy_only=False)
    bins = table["global_bin"].to_numpy(zero_copy_only=False)
    order = np.lexsort((bins, adc))
    if not np.array_equal(order, np.arange(table.num_rows)):
        table = table.take(pa.array(order))
    return table


def list_matrix(column: pa.ChunkedArray, width: int, dtype: np.dtype[Any]) -> np.ndarray:
    values = column.combine_chunks().values.to_numpy(zero_copy_only=False)
    return np.asarray(values, dtype=dtype).reshape(len(column), width)


def payload_tag(name: str, raw: bytes, level: int = 6) -> tuple[str, dict[str, Any]]:
    packed = gzip.compress(raw, compresslevel=level, mtime=0)
    encoded = base64.b64encode(packed).decode("ascii")
    tag = f'<script type="application/octet-stream" id="payload-{html.escape(name)}">{encoded}</script>'
    return tag, {
        "name": name,
        "raw_bytes": len(raw),
        "gzip_bytes": len(packed),
        "sha256_raw": hashlib.sha256(raw).hexdigest(),
    }


def read_native_chunk(scan_root: Path, block: int, chunk: int) -> np.ndarray:
    path = scan_root / "mean_power_count2" / f"{chunk}.0.{block}"
    data = np.fromfile(path, dtype="<f8")
    expected = 100 * ADC_COUNT * BLOCK_BINS
    if data.size != expected:
        raise RuntimeError(f"{path}: expected {expected} values, got {data.size}")
    return data.reshape(100, ADC_COUNT, BLOCK_BINS)


def quantize_rows_u16(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    minimum = np.min(values, axis=-1).astype(np.float32)
    maximum = np.max(values, axis=-1).astype(np.float32)
    scale = ((maximum - minimum) / 65535.0).astype(np.float32)
    scale[scale == 0] = 1.0
    quantized = np.rint((values - minimum[..., None]) / scale[..., None])
    return np.clip(quantized, 0, 65535).astype("<u2"), minimum, scale


def quantize_rows_u8(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    minimum = np.min(values, axis=-1).astype(np.float32)
    maximum = np.max(values, axis=-1).astype(np.float32)
    scale = ((maximum - minimum) / 255.0).astype(np.float32)
    scale[scale == 0] = 1.0
    quantized = np.rint((values - minimum[..., None]) / scale[..., None])
    return np.clip(quantized, 0, 255).astype(np.uint8), minimum, scale


def full_metrics_csv(root: Path) -> tuple[bytes, list[str]]:
    buffer = io.StringIO(newline="")
    writer: csv.writer | None = None
    output_columns: list[str] = []
    scalar_columns: list[str] = []
    for scan in SCAN_LABELS:
        for block in range(BLOCK_COUNT):
            table = ordered_metric_table(root, scan, block)
            if writer is None:
                scalar_columns = [name for name in table.column_names if name not in METRIC_LIST_COLUMNS]
                output_columns = list(scalar_columns)
                for name, suffixes in METRIC_LIST_COLUMNS.items():
                    output_columns.extend(f"{name}_{suffix}" for suffix in suffixes)
                writer = csv.writer(buffer, lineterminator="\n")
                writer.writerow(output_columns)
            scalar = {name: table[name].to_pylist() for name in scalar_columns}
            lists = {
                name: list_matrix(table[name], len(suffixes), np.float64)
                for name, suffixes in METRIC_LIST_COLUMNS.items()
            }
            for row in range(table.num_rows):
                values = [scalar[name][row] for name in scalar_columns]
                for name in METRIC_LIST_COLUMNS:
                    values.extend(lists[name][row].tolist())
                writer.writerow(values)
    return buffer.getvalue().encode("utf-8"), output_columns


def collect_report_data(root: Path, config: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    quick = np.empty((3, ADC_COUNT, BIN_COUNT, len(QUICK_FIELDS)), dtype="<f4")
    acf = np.empty((3, ADC_COUNT, BIN_COUNT, 27), dtype="<f4")
    adev = np.empty((3, ADC_COUNT, BIN_COUNT, 12), dtype="<f4")
    psd_quantized: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    rf_hz = np.empty(BIN_COUNT, dtype="<f8")
    flags: dict[str, int] = {}

    cross = np.empty((ADC_COUNT, BIN_COUNT), dtype=np.float32)
    for block in range(BLOCK_COUNT):
        path = root / "cross_scan_reproducibility" / f"block={block:02d}" / "part.parquet"
        table = pq.read_table(path)
        matrix = table["between_scan_fractional_std"].to_numpy().reshape(ADC_COUNT, BLOCK_BINS)
        cross[:, block * BLOCK_BINS : (block + 1) * BLOCK_BINS] = matrix

    for scan_index, scan in enumerate(SCAN_LABELS):
        for block in range(BLOCK_COUNT):
            metrics = ordered_metric_table(root, scan, block)
            temporal = ordered_temporal_table(root, scan, block)
            sl = slice(block * BLOCK_BINS, (block + 1) * BLOCK_BINS)
            for adc in range(ADC_COUNT):
                rows = slice(adc * BLOCK_BINS, (adc + 1) * BLOCK_BINS)
                if scan_index == 0 and adc == 0:
                    rf_hz[sl] = metrics["rf_hz"].to_numpy()[rows]
                integration_std = list_matrix(metrics["integration_std_count2"], 4, np.float32)[rows]
                sigma_ratio = list_matrix(metrics["sigma_over_theory"], 4, np.float32)[rows]
                values = (
                    metrics["mean_power_count2"].to_numpy()[rows],
                    metrics["power_density_count2_per_hz"].to_numpy()[rows],
                    metrics["native_std_power_count2"].to_numpy()[rows],
                    *[integration_std[:, index] for index in range(4)],
                    *[sigma_ratio[:, index] for index in range(4)],
                    metrics["spectral_kurtosis"].to_numpy()[rows],
                    metrics["temperature_r2"].to_numpy()[rows],
                    cross[adc, sl],
                )
                quick[scan_index, adc, sl, :] = np.stack(values, axis=1).astype(np.float32)
                acf[scan_index, adc, sl, :] = list_matrix(
                    temporal["acf_constant_removed"], 27, np.float32
                )[rows]
                adev[scan_index, adc, sl, :] = list_matrix(
                    temporal["adev_overlap_raw_count2"], 12, np.float32
                )[rows]
                psd = list_matrix(temporal["psd_raw_count4_per_hz"], 1025, np.float32)[rows]
                log_psd = np.log10(np.maximum(psd, np.finfo(np.float32).tiny))
                psd_quantized[(scan_index, adc, block)] = quantize_rows_u8(log_psd)
            if scan_index == 0:
                for value in metrics["data_quality_flags"].to_pylist():
                    key = value or "none"
                    flags[key] = flags.get(key, 0) + 1

    tags: list[str] = []
    payloads: list[dict[str, Any]] = []

    def add(name: str, raw: bytes, level: int = 6) -> None:
        tag, info = payload_tag(name, raw, level)
        tags.append(tag)
        payloads.append(info)

    add("quick-f32", quick.tobytes(order="C"))
    add("rf-hz-f64", rf_hz.tobytes(order="C"))
    for scan_index, scan in enumerate(SCAN_LABELS):
        for adc in range(ADC_COUNT):
            add(f"acf-{scan}-{adc}-f32", acf[scan_index, adc].tobytes(order="C"))
            add(f"adev-{scan}-{adc}-f32", adev[scan_index, adc].tobytes(order="C"))
            q_parts, min_parts, scale_parts = [], [], []
            for block in range(BLOCK_COUNT):
                quantized, minimum, scale = psd_quantized[(scan_index, adc, block)]
                q_parts.append(quantized)
                min_parts.append(minimum)
                scale_parts.append(scale)
            add(f"psd-{scan}-{adc}-u8", np.concatenate(q_parts).tobytes(order="C"), 1)
            psd_meta = np.stack((np.concatenate(min_parts), np.concatenate(scale_parts)), axis=1)
            add(f"psdmeta-{scan}-{adc}-f32", psd_meta.astype("<f4").tobytes(order="C"))

    scan_a = Path(config["scans"][0]["path"])
    for adc in range(ADC_COUNT):
        native = np.empty((BIN_COUNT, 1500), dtype=np.float32)
        dynamic_min = np.empty((900, BIN_COUNT), dtype=np.float32)
        dynamic_max = np.empty((900, BIN_COUNT), dtype=np.float32)
        for block in range(BLOCK_COUNT):
            sl = slice(block * BLOCK_BINS, (block + 1) * BLOCK_BINS)
            first = []
            for chunk in range(900):
                values = read_native_chunk(scan_a, block, chunk)
                if chunk < 15:
                    first.append(values[:, adc, :].astype(np.float32))
                log_values = np.log10(np.maximum(values[:, adc, :], np.finfo(np.float64).tiny))
                dynamic_min[chunk, sl] = np.min(log_values, axis=0).astype(np.float32)
                dynamic_max[chunk, sl] = np.max(log_values, axis=0).astype(np.float32)
            native[sl] = np.concatenate(first, axis=0).T
        native_q, native_min, native_scale = quantize_rows_u16(native)
        add(f"native15-A-{adc}-u16", native_q.tobytes(order="C"), 1)
        native_meta = np.stack((native_min, native_scale), axis=1).astype("<f4")
        add(f"native15meta-A-{adc}-f32", native_meta.tobytes(order="C"))
        combined = np.stack((dynamic_min, dynamic_max), axis=0)
        lo = float(np.min(combined))
        scale = float((np.max(combined) - lo) / 255.0) or 1.0
        dynamic_q = np.clip(np.rint((combined - lo) / scale), 0, 255).astype(np.uint8)
        add(f"dynamic-A-{adc}-u8", dynamic_q.tobytes(order="C"), 1)
        payloads[-1]["quantization_min_log10"] = lo
        payloads[-1]["quantization_scale_log10"] = scale

    time_metrics = pq.read_table(root / "time_control_metrics.parquet").to_pylist()
    time_series = pq.read_table(root / "time_control_10ms_series.parquet").to_pylist()
    time_json = json.dumps({"metrics": time_metrics, "series": time_series}, separators=(",", ":"), allow_nan=False)
    add("time-json", time_json.encode("utf-8"))

    csv_bytes, csv_columns = full_metrics_csv(root)
    add("metrics-csv", csv_bytes, 9)

    finite_quick = quick[np.isfinite(quick)]
    if finite_quick.size != quick.size:
        raise RuntimeError("non-finite quick metric values")
    summary = {
        "format": "T510_STAGE35_S2_HTML_DATA_V1",
        "quick_fields": QUICK_FIELDS,
        "quick_shape": list(quick.shape),
        "acf_shape_per_scan_adc": [BIN_COUNT, 27],
        "adev_shape_per_scan_adc": [BIN_COUNT, 12],
        "psd_shape_per_scan_adc": [BIN_COUNT, 1025],
        "native15_shape_per_adc": [BIN_COUNT, 1500],
        "dynamic_shape_per_adc": [2, 900, BIN_COUNT],
        "detail_native_scan": "A",
        "metric_csv_columns": csv_columns,
        "metric_csv_rows": 3 * ADC_COUNT * BIN_COUNT,
        "quality_flag_counts_scan_a": flags,
        "payloads": payloads,
    }
    return summary, tags, payloads


def quantile_text(values: np.ndarray) -> str:
    q = np.quantile(values[np.isfinite(values)], [0.05, 0.5, 0.95])
    return f"{q[1]:.6g} (P05 {q[0]:.6g}, P95 {q[2]:.6g})"


def science_summary(root: Path) -> dict[str, Any]:
    values: dict[str, list[float]] = {
        "sigma_ratio_15": [], "temp_r2": [], "acf_1s": [], "adev_15": [], "sk": [], "cross": []
    }
    per_adc: list[dict[str, Any]] = []
    for adc in range(ADC_COUNT):
        adc_values = {key: [] for key in values}
        for scan in SCAN_LABELS:
            for block in range(BLOCK_COUNT):
                metrics = ordered_metric_table(root, scan, block)
                temporal = ordered_temporal_table(root, scan, block)
                rows = slice(adc * BLOCK_BINS, (adc + 1) * BLOCK_BINS)
                ratio = list_matrix(metrics["sigma_over_theory"], 4, np.float64)[rows, 2]
                acf = list_matrix(temporal["acf_constant_removed"], 27, np.float64)[rows, 22]
                adev = list_matrix(temporal["adev_overlap_raw_count2"], 12, np.float64)[rows, 10]
                current = {
                    "sigma_ratio_15": ratio,
                    "temp_r2": metrics["temperature_r2"].to_numpy()[rows],
                    "acf_1s": acf,
                    "adev_15": adev,
                    "sk": metrics["spectral_kurtosis"].to_numpy()[rows],
                }
                for key, array in current.items():
                    values[key].extend(array.tolist())
                    adc_values[key].extend(array.tolist())
        for block in range(BLOCK_COUNT):
            cross = pq.read_table(root / "cross_scan_reproducibility" / f"block={block:02d}" / "part.parquet")
            rows = slice(adc * BLOCK_BINS, (adc + 1) * BLOCK_BINS)
            array = cross["between_scan_fractional_std"].to_numpy()[rows]
            values["cross"].extend(array.tolist())
            adc_values["cross"].extend(array.tolist())
        per_adc.append({key: quantile_text(np.asarray(item)) for key, item in adc_values.items()})
    return {
        "overall": {key: quantile_text(np.asarray(item)) for key, item in values.items()},
        "per_adc": per_adc,
    }


CSS = r"""
:root{--bg:#07111f;--panel:#0d1b2d;--ink:#e8f0fa;--muted:#9fb1c7;--line:#28415f;--cyan:#55d6d0;--amber:#ffbd59;--violet:#ad8cff;--red:#ff7188}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}header{padding:36px max(24px,calc((100vw - 1280px)/2));background:linear-gradient(135deg,#0b2940,#161c38)}h1{margin:0 0 8px;font-size:clamp(28px,4vw,48px)}h2{margin-top:34px}h3{margin-top:22px}.sub,.note{color:var(--muted)}main{max-width:1320px;margin:auto;padding:20px}.card,.adc{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}.metric{font-size:24px;color:var(--cyan)}code{overflow-wrap:anywhere;color:#c6e4ff}canvas{display:block;width:100%;height:280px;background:#081421;border:1px solid #20364e;border-radius:8px}.heat{height:220px}.dynamic{height:340px}.controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:10px 0}.controls label{display:grid;gap:4px}.controls input,.controls select,.controls button,button{background:#12263c;color:var(--ink);border:1px solid #3e5c7a;border-radius:6px;padding:8px}button{cursor:pointer}.badge{display:inline-block;border:1px solid var(--cyan);color:var(--cyan);border-radius:999px;padding:3px 9px;margin-right:6px}details>summary{cursor:pointer;font-size:21px;font-weight:650}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);text-align:right;padding:6px;white-space:nowrap}th:first-child,td:first-child{text-align:left}.scroll{overflow:auto;max-height:520px}.warning{border-left:4px solid var(--amber);padding:10px 14px;background:#342a16}.provenance{font-size:12px}.tabline{display:flex;gap:8px;flex-wrap:wrap}.status{color:var(--cyan)}@media print{body{background:white;color:black}.card,.adc{break-inside:avoid;background:white;border-color:#aaa}canvas{background:white}}
"""


JS = r"""
'use strict';
const META=JSON.parse(document.getElementById('report-meta').textContent);const cache=new Map();
async function bytes(name){if(cache.has(name))return cache.get(name);const b64=document.getElementById('payload-'+name).textContent.trim();const raw=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));const stream=new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'));const out=new Uint8Array(await new Response(stream).arrayBuffer());cache.set(name,out);return out}
async function typed(name,Type){const b=await bytes(name);return new Type(b.buffer,b.byteOffset,b.byteLength/Type.BYTES_PER_ELEMENT)}
const colors=['#55d6d0','#ffbd59','#ad8cff','#ff7188','#6fb1ff'];
function finiteRange(series){let lo=Infinity,hi=-Infinity;for(const a of series)for(const v of a)if(Number.isFinite(v)){lo=Math.min(lo,v);hi=Math.max(hi,v)}if(!(hi>lo)){lo-=1;hi+=1}return[lo,hi]}
function line(canvas,x,series,labels,title,logY=false){const c=canvas.getContext('2d'),w=canvas.width=1200,h=canvas.height=360,m={l:78,r:22,t:34,b:48};c.fillStyle='#081421';c.fillRect(0,0,w,h);let transformed=series.map(a=>Array.from(a,v=>logY?Math.log10(Math.max(v,1e-38)):v));let[lo,hi]=finiteRange(transformed);c.strokeStyle='#34506c';c.fillStyle='#9fb1c7';c.font='13px system-ui';for(let i=0;i<6;i++){let y=m.t+(h-m.t-m.b)*i/5;c.beginPath();c.moveTo(m.l,y);c.lineTo(w-m.r,y);c.stroke();let v=hi-(hi-lo)*i/5;c.fillText((logY?'10^':'')+v.toPrecision(3),4,y+4)}series.forEach((a,j)=>{c.strokeStyle=colors[j%colors.length];c.lineWidth=1.5;c.beginPath();for(let i=0;i<a.length;i++){let xx=m.l+(w-m.l-m.r)*(x[i]-x[0])/(x[x.length-1]-x[0]||1),v=transformed[j][i],yy=h-m.b-(h-m.t-m.b)*(v-lo)/(hi-lo);if(i)c.lineTo(xx,yy);else c.moveTo(xx,yy)}c.stroke();c.fillStyle=colors[j%colors.length];c.fillText(labels[j],m.l+130*j,m.t-11)});c.fillStyle='#e8f0fa';c.fillText(title,m.l,m.t-11);c.fillStyle='#9fb1c7';c.fillText(x[0].toPrecision(6),m.l,h-16);c.fillText(x[x.length-1].toPrecision(6),w-m.r-85,h-16)}
function heat(canvas,data,rows,cols,title,centerZero=false){const c=canvas.getContext('2d');canvas.width=cols;canvas.height=rows;let lo=Infinity,hi=-Infinity;for(const v of data)if(Number.isFinite(v)){lo=Math.min(lo,v);hi=Math.max(hi,v)}if(centerZero){let a=Math.max(Math.abs(lo),Math.abs(hi));lo=-a;hi=a}let img=c.createImageData(cols,rows);for(let i=0;i<data.length;i++){let z=Math.max(0,Math.min(1,(data[i]-lo)/(hi-lo||1))),r=Math.round(255*Math.max(0,2*z-1)),b=Math.round(255*Math.max(0,1-2*z)),g=Math.round(220*(1-Math.abs(2*z-1)));img.data[4*i]=r;img.data[4*i+1]=g;img.data[4*i+2]=b;img.data[4*i+3]=255}c.putImageData(img,0,0);canvas.title=`${title}; range ${lo.toPrecision(4)} .. ${hi.toPrecision(4)}`}
let QUICK=null,RF=null;async function core(){if(!QUICK){QUICK=await typed('quick-f32',Float32Array);RF=await typed('rf-hz-f64',Float64Array)}return QUICK}
function qi(scan,adc,bin,field){return ((((scan*8+adc)*4096+bin)*META.quick_fields.length)+field)}
function qv(scan,adc,bin,name){return QUICK[qi(scan,adc,bin,META.quick_fields.indexOf(name))]}
async function renderADC(adc){await core();const box=document.querySelector(`[data-adc="${adc}"]`),scan=Number(box.querySelector('.scan').value),bin=Math.max(0,Math.min(4095,Number(box.querySelector('.bin').value))),scanName=['A','B','C'][scan];let bands=[];for(let s=0;s<3;s++){let a=new Float32Array(4096);for(let k=0;k<4096;k++)a[k]=qv(s,adc,k,'mean_power_count2');bands.push(a)}line(box.querySelector('.band'),RF,bands,['A','B','C'],`ADC${adc} complete 4096-bin bandpass`);let zx=Array.from(RF.slice(3296,3361)),zs=bands.map(a=>Array.from(a.slice(3296,3361)));line(box.querySelector('.spur'),zx,zs,['A','B','C'],`ADC${adc} 960 MHz fixed-item neighborhood (bin 3328 retained)`);let map=new Float32Array(4*4096);for(let t=0;t<4;t++)for(let k=0;k<4096;k++)map[t*4096+k]=qv(scan,adc,k,`integration_std_${['2s','4s','15s','30s'][t]}`);heat(box.querySelector('.tauheat'),map,4,4096,`${scanName} frequency x tau absolute scatter`);let ac=await typed(`acf-${scanName}-${adc}-f32`,Float32Array),acmap=new Float32Array(27*4096);for(let k=0;k<4096;k++)for(let j=0;j<27;j++)acmap[j*4096+k]=ac[k*27+j];heat(box.querySelector('.acfheat'),acmap,27,4096,`${scanName} frequency x lag ACF`,true);let acLine=[];for(let j=0;j<27;j++)acLine.push(ac[bin*27+j]);line(box.querySelector('.acfline'),META.acf_lag_seconds,[acLine],['ACF'],`${scanName} ADC${adc} bin ${bin} ACF`);let ad=await typed(`adev-${scanName}-${adc}-f32`,Float32Array),adLine=[];for(let j=0;j<12;j++)adLine.push(ad[bin*12+j]);line(box.querySelector('.adev'),META.allan_seconds,[adLine],['raw overlap'],`${scanName} ADC${adc} bin ${bin} Allan deviation`,true);let tau=[2,4,15,30],std=tau.map((_,i)=>qv(scan,adc,bin,`integration_std_${['2s','4s','15s','30s'][i]}`)),ratio=tau.map((_,i)=>qv(scan,adc,bin,`sigma_over_theory_${['2s','4s','15s','30s'][i]}`));line(box.querySelector('.integration'),tau,[std],['absolute std count²'],`${scanName} ADC${adc} bin ${bin} integration`);box.querySelector('.facts').textContent=`RF ${(RF[bin]/1e6).toFixed(6)} MHz | mean ${qv(scan,adc,bin,'mean_power_count2').toPrecision(8)} count²/channel | 15 s sigma/theory ${ratio[2].toPrecision(6)} | SK ${qv(scan,adc,bin,'spectral_kurtosis').toPrecision(6)} | temperature R² ${qv(scan,adc,bin,'temperature_r2').toPrecision(5)}`;let pq=await typed(`psd-${scanName}-${adc}-u8`,Uint8Array),pm=await typed(`psdmeta-${scanName}-${adc}-f32`,Float32Array),p=new Float32Array(1025),pmin=pm[bin*2],pscale=pm[bin*2+1];for(let j=0;j<1025;j++)p[j]=10**(pmin+pscale*pq[bin*1025+j]);let freq=Array.from({length:1025},(_,i)=>i*50/1024);line(box.querySelector('.psd'),freq,[p],['raw'],`${scanName} ADC${adc} bin ${bin} temporal PSD`,true);let nq=await typed(`native15-A-${adc}-u16`,Uint16Array),nm=await typed(`native15meta-A-${adc}-f32`,Float32Array),native=new Float32Array(1500),nmin=nm[bin*2],nscale=nm[bin*2+1];for(let j=0;j<1500;j++)native[j]=nmin+nscale*nq[bin*1500+j];let nt=Array.from({length:1500},(_,i)=>i*.01);line(box.querySelector('.native'),nt,[native],['Scan A'],`ADC${adc} bin ${bin}: all 1,500 native 10 ms buckets in registered 15 s window`);hist(box.querySelector('.hist'),native,48,`ADC${adc} bin ${bin} native-window distribution`);let dq=await typed(`dynamic-A-${adc}-u8`,Uint8Array),pi=META.payload_index[`dynamic-A-${adc}-u8`],dynmin=new Float32Array(900*4096),dynmax=new Float32Array(900*4096);for(let i=0;i<dynmin.length;i++){dynmin[i]=pi.quantization_min_log10+pi.quantization_scale_log10*dq[i];dynmax[i]=pi.quantization_min_log10+pi.quantization_scale_log10*dq[900*4096+i]}heat(box.querySelector('.dynamicmin'),dynmin,900,4096,'Scan A 1 s minimum envelope dynamic spectrum');heat(box.querySelector('.dynamicmax'),dynmax,900,4096,'Scan A 1 s maximum envelope dynamic spectrum');box.querySelector('.binexport').onclick=()=>download(`stage35-${scanName}-adc${adc}-bin${bin}.json`,JSON.stringify({scan:scanName,adc,global_bin:bin,rf_hz:RF[bin],mean_power_count2:qv(scan,adc,bin,'mean_power_count2'),integration_tau_s:tau,integration_std_count2:std,sigma_over_theory:ratio,acf_lag_s:META.acf_lag_seconds,acf:Array.from(acLine),allan_tau_s:META.allan_seconds,adev_overlap_raw_count2:Array.from(adLine),psd_frequency_hz:freq,psd_raw_display:Array.from(p),native_scan:'A',native_time_s:nt,native_power_display_count2:Array.from(native)},null,2),'application/json');box.dataset.ready='1'}
function hist(canvas,a,bins,title){let lo=Math.min(...a),hi=Math.max(...a),counts=new Uint32Array(bins);for(const v of a)counts[Math.min(bins-1,Math.floor((v-lo)/(hi-lo||1)*bins))]++;let x=Array.from({length:bins},(_,i)=>lo+(i+.5)*(hi-lo)/bins);line(canvas,x,[counts],['count'],title)}
document.querySelectorAll('.adc').forEach(box=>{const adc=Number(box.dataset.adc);box.querySelectorAll('.scan,.bin').forEach(x=>x.addEventListener('change',()=>renderADC(adc)));box.addEventListener('toggle',()=>{if(box.open&&!box.dataset.ready)renderADC(adc)});box.querySelector('.render').onclick=()=>renderADC(adc)});
let CSV_TEXT=null;async function getCSV(){if(CSV_TEXT===null)CSV_TEXT=new TextDecoder().decode(await bytes('metrics-csv'));return CSV_TEXT}
async function searchTable(){const text=await getCSV(),lines=text.split('\n'),header=lines[0].split(','),iscan=header.indexOf('scan_label'),iadc=header.indexOf('adc_id'),ibin=header.indexOf('global_bin'),s=document.getElementById('tscan').value,a=document.getElementById('tadc').value,b0=Number(document.getElementById('tbin0').value),b1=Number(document.getElementById('tbin1').value),matches=[lines[0]];for(let i=1;i<lines.length&&matches.length<=501;i++){if(!lines[i])continue;let p=lines[i].split(',');if((s==='*'||p[iscan]===s)&&(a==='*'||p[iadc]===a)&&Number(p[ibin])>=b0&&Number(p[ibin])<=b1)matches.push(lines[i])}renderTable(matches,header);window.filteredCSV=matches.join('\n')+'\n'}
function renderTable(lines,header){let shown=lines.slice(1,201),out='<table><thead><tr>'+header.map(x=>`<th>${x}</th>`).join('')+'</tr></thead><tbody>';for(const line of shown)out+='<tr>'+line.split(',').map(x=>`<td>${x}</td>`).join('')+'</tr>';document.getElementById('tableout').innerHTML=out+'</tbody></table>';document.getElementById('tablestatus').textContent=`matched ${lines.length-1}; showing ${shown.length}`}
function download(name,text,type='text/csv'){let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
document.getElementById('tsearch').onclick=searchTable;document.getElementById('texport').onclick=()=>download('stage35_filtered_metrics.csv',window.filteredCSV||'');document.getElementById('tfull').onclick=async()=>download('stage35_complete_metrics.csv',await getCSV());
core().then(()=>{document.querySelector('.adc').open=true});
async function renderTime(){let data=JSON.parse(new TextDecoder().decode(await bytes('time-json'))),label=document.getElementById('time-select').value,rows=data.series.filter(x=>x.control_label===label).sort((a,b)=>a.adc_id-b.adc_id),x=Array.from({length:3000},(_,i)=>i*.01);line(document.getElementById('time-rms'),x,rows.map(r=>r.complex_rms_adu),rows.map(r=>`ADC${r.adc_id}`),`${label} complex RMS ADU`);line(document.getElementById('time-iq'),x,rows.flatMap(r=>[r.mean_i_adu,r.mean_q_adu]),rows.flatMap(r=>[`ADC${r.adc_id} I`,`ADC${r.adc_id} Q`]),`${label} mean I/Q ADU`)}
document.getElementById('time-select').onchange=renderTime;renderTime();
"""


def adc_sections() -> str:
    sections = []
    for adc in range(ADC_COUNT):
        sections.append(f"""
<details class="adc" data-adc="{adc}"><summary>ADC{adc} — 完整频带、时间尺度与任意 bin 细节</summary>
<div class="controls"><label>扫描<select class="scan"><option value="0">A</option><option value="1">B</option><option value="2">C</option></select></label><label>global_bin<input class="bin" type="number" min="0" max="4095" value="3328"></label><button class="render">刷新</button><button class="binexport">导出当前bin JSON</button><span class="facts note"></span></div>
<div class="grid"><div><h3>4096-bin 带通</h3><canvas class="band"></canvas></div><div><h3>固定 960 MHz 杂散及邻近 bin 放大</h3><p>中心 1020 MHz 时，960 MHz 对应 global_bin 3328；原始bin不删除或插值。</p><canvas class="spur"></canvas></div></div>
<h3>Scan A 全 bin 动态谱</h3><p class="note">900 s中的每个1 s窗均用全100个原生10 ms桶生成min/max envelope；统计计算未使用渲染层。</p><div class="grid"><canvas class="dynamicmin dynamic heat"></canvas><canvas class="dynamicmax dynamic heat"></canvas></div>
<div class="grid"><div><h3>frequency × tau 绝对散布</h3><canvas class="tauheat heat"></canvas></div><div><h3>frequency × lag ACF</h3><canvas class="acfheat heat"></canvas></div></div>
<div class="grid"><div><h3>选定 bin：ACF</h3><canvas class="acfline"></canvas></div><div><h3>选定 bin：Allan deviation</h3><canvas class="adev"></canvas></div><div><h3>选定 bin：temporal PSD</h3><canvas class="psd"></canvas></div><div><h3>选定 bin：分布</h3><canvas class="hist"></canvas></div></div>
<h3>选定 bin：2/4/15/30 s 绝对散布</h3><canvas class="integration"></canvas>
<h3>选定 bin：15 s 全原生桶</h3><p class="note">固定展示独立 Scan A 的首个已注册15 s窗，1500/1500个10 ms桶全部绘制。为控制单文件体积，绘图值按每条曲线min/scale量化为uint16；权威float64值、统计量和完整900 s序列仍在Zarr/Parquet，不以显示编码重算结论。</p><canvas class="native"></canvas>
</details>""")
    return "\n".join(sections)


def make_html(meta: dict[str, Any], tags: Iterable[str], science: dict[str, Any]) -> str:
    overall = science["overall"]
    adc_rows = "".join(
        f"<tr><td>ADC{i}</td><td>{row['sigma_ratio_15']}</td><td>{row['acf_1s']}</td><td>{row['adev_15']}</td><td>{row['cross']}</td><td>{row['temp_r2']}</td></tr>"
        for i, row in enumerate(science["per_adc"])
    )
    payload_index = {item["name"]: item for item in meta["payloads"]}
    browser_meta = {
        **{key: value for key, value in meta.items() if key != "payloads"},
        "payload_index": payload_index,
        "acf_lag_seconds": [0,.01,.02,.03,.04,.05,.06,.07,.08,.09,.1,.11,.12,.13,.14,.15,.16,.17,.18,.19,.2,.5,1,2,4,8,15],
        "allan_seconds": [.01,.02,.05,.1,.2,.5,1,2,4,8,15,30],
    }
    tag_text = "\n".join(tags)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stage 35 未定标 50 Ω 自相关噪声报告</title><style>{CSS}</style></head><body>
<header><span class="badge">Stage 35 / S2</span><span class="badge">单文件离线报告</span><h1>未定标 50 Ω 自相关与时间噪声</h1><p class="sub">T510 · 8 ADC · 4096 channels · 10 ms native buckets · A/B/C three independent 900 s scans</p></header><main>
<section class="card warning"><strong>定标边界：</strong>本报告只使用 ADU、F-engine count、count²/channel、count²/Hz 与 count⁴。单个室温50 Ω工作点不能给出 K、Jy、SEFD、连接器dBm或 T_sys。</section>
<section class="card"><h2>数据身份与完整性</h2><div class="grid"><div><div class="metric">98,304</div>逐扫描 ADC/bin 指标行</div><div><div class="metric">32,768</div>跨扫描复现性行</div><div><div class="metric">48</div>TIME pre/post 控制行</div><div><div class="metric">0</div>正式窗口 drop/gap/duplicate/reorder</div></div><p class="provenance">分析 manifest SHA-256：<code>{meta['analysis_manifest_sha256']}</code><br>分析根：<code>{html.escape(meta['analysis_root'])}</code><br>原始队列 manifest SHA-256：<code>{meta['queue_manifest_sha256']}</code></p></section>
<section class="card"><h2>全样本统计概览</h2><p>以下均为逐 ADC、逐真实 bin 的分布摘要，不是“通过比例”。括号为P05/P95。</p><div class="grid"><div><h3>15 s 实测散布 / ENBW白噪声理论</h3><div class="metric">{overall['sigma_ratio_15']}</div></div><div><h3>1 s ACF</h3><div class="metric">{overall['acf_1s']}</div></div><div><h3>15 s overlapping ADEV</h3><div class="metric">{overall['adev_15']}</div></div><div><h3>A/B/C 扫描间分数散布</h3><div class="metric">{overall['cross']}</div></div></div><div class="scroll"><table><thead><tr><th>ADC</th><th>15 s σ/理论</th><th>ACF(1 s)</th><th>ADEV(15 s), count²</th><th>跨扫描分数散布</th><th>温度回归 R²</th></tr></thead><tbody>{adc_rows}</tbody></table></div><p class="note">原始结果优先；constant-removed与PL温度回归版本保留在权威表中作为明确标记的对照，不能替代原始测量。</p></section>
<section class="card"><h2>TIME ADU 控制</h2><p>六组相邻TIME_ONLY观测（A/B/C各pre/post）均为RFDC/TIME post-DDC complex IQ16 ADU，不是3.84 GS/s converter原码，也不与SPEC同时采集。每张图显示全30 s的3,000个10 ms桶。</p><div class="controls"><label>控制段<select id="time-select"><option>A-pre</option><option>A-post</option><option>B-pre</option><option>B-post</option><option>C-pre</option><option>C-post</option></select></label><button id="time-export">导出 TIME JSON</button></div><div class="grid"><canvas id="time-rms"></canvas><canvas id="time-iq"></canvas></div></section>
<h2>逐 ADC 科学面板</h2>{adc_sections()}
<section class="card"><h2>完整数值表</h2><p>内嵌CSV包含98,304行及所有metrics_by_scan标量、展开后的2/4/15/30 s数组字段。筛选结果只分页显示前200行，导出不截断。</p><div class="controls"><label>scan<select id="tscan"><option>*</option><option>A</option><option>B</option><option>C</option></select></label><label>ADC<select id="tadc"><option>*</option>{''.join(f'<option>{i}</option>' for i in range(8))}</select></label><label>bin from<input id="tbin0" type="number" min="0" max="4095" value="3328"></label><label>to<input id="tbin1" type="number" min="0" max="4095" value="3328"></label><button id="tsearch">检索</button><button id="texport">导出筛选CSV</button><button id="tfull">导出完整CSV</button></div><div id="tablestatus" class="status"></div><div id="tableout" class="scroll"></div></section>
<section class="card"><h2>方法与限制</h2><ul><li>统计输入是全部有效10 ms桶；没有填零、默认插值、代表bin或ADC平均替代。</li><li>2/4/15/30 s为非重叠科学积分；Allan主网格最大30 s，ACF主视野0–15 s。</li><li>Welch PSD使用100 Hz原生序列、2048点Hann窗、1024重叠；浏览器显示用逐行uint8 log-PSD编码，权威float32数组保留于Parquet。</li><li>bootstrap使用128次保持时间结构的circular block抽样，种子3507；block长度由实测ACF确定并逐block记录。</li><li>固定960 MHz项及相邻bin未删除；全带原始表始终可检索和导出。</li></ul></section>
<section class="card provenance"><h2>内嵌数据账本</h2><pre>{html.escape(json.dumps(meta, indent=2, ensure_ascii=False))}</pre></section>
</main><script type="application/json" id="report-meta">{json.dumps(browser_meta, separators=(',',':')).replace('</', '<\\/')}</script>\n{tag_text}\n<script>{JS}
document.getElementById('time-export').onclick=async()=>download('time_capture_controls.json',new TextDecoder().decode(await bytes('time-json')),'application/json');
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args()
    root = args.analysis_root.resolve()
    manifest_path = root / "analysis_manifest.json"
    actual_manifest = sha256_file(manifest_path)
    if actual_manifest != args.expected_manifest_sha256:
        raise RuntimeError("analysis manifest SHA-256 mismatch")
    manifest = load_json(manifest_path)
    if not manifest.get("complete"):
        raise RuntimeError("analysis manifest is not complete")
    config = load_json(root / "analysis_config.json")
    state = load_json(root / "analysis_state.json")
    summary = load_json(root / "analysis_summary.json")
    if state.get("status") != "completed" or state.get("error") is not None or summary.get("status") != "PASS":
        raise RuntimeError("analysis final state is not accepted")

    data_meta, tags, _ = collect_report_data(root, config)
    science = science_summary(root)
    meta = {
        **data_meta,
        "analysis_root": str(root),
        "analysis_manifest_sha256": actual_manifest,
        "queue_manifest_sha256": config["queue_manifest_sha256"],
        "analysis_summary": summary,
        "science_summary": science,
        "rendering_contract": {
            "statistics": "authoritative Parquet/Zarr, no plot downsampling used for statistics",
            "bandpass": "all 4096 bins in canvas backing store",
            "dynamic": "Scan A, 1 s min/max envelope from all 100 native 10 ms buckets",
            "native_detail": "Scan A, first registered 15 s, all 1500 native bucket positions; uint16 per-row display encoding",
            "psd": "all 1025 bins; uint8 per-row log10 display encoding",
        },
    }
    document = make_html(meta, tags, science)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    partial.write_text(document, encoding="utf-8")
    with partial.open("rb") as stream:
        os.fsync(stream.fileno())
    partial.replace(args.output)
    digest = sha256_file(args.output)
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(
        f"{digest}  {args.output.name}\n", encoding="ascii"
    )
    report_manifest = {
        "format": "T510_STAGE35_S2_HTML_REPORT_MANIFEST_V1",
        "schema_version": 1,
        "complete": True,
        "report": {
            "path": str(args.output),
            "bytes": args.output.stat().st_size,
            "sha256": digest,
        },
        "generator": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "analysis_root": str(root),
        "analysis_manifest_sha256": actual_manifest,
        "payloads": data_meta["payloads"],
        "metric_csv_rows": data_meta["metric_csv_rows"],
        "rendering_contract": meta["rendering_contract"],
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(report_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_sha = sha256_file(manifest_path)
    manifest_path.with_suffix(manifest_path.suffix + ".sha256").write_text(
        f"{manifest_sha}  {manifest_path.name}\n", encoding="ascii"
    )
    print(json.dumps({"status": "PASS", "output": str(args.output), "bytes": args.output.stat().st_size, "sha256": digest, "analysis_manifest_sha256": actual_manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
