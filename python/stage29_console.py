from __future__ import annotations

import asyncio
from html import escape
import json
from pathlib import Path
import urllib.request
from typing import Any

from .stage29 import (
    DacChannelConfig,
    DEFAULT_SOURCE_IP,
    DEFAULT_SOURCE_MAC,
    EXPECTED_CORE_VERSION,
    FlowDestination,
    Stage29Config,
    Stage29Controller,
)


COLORS = ["#0b5cad", "#c45200", "#217a3b", "#b3261e", "#6f42c1", "#5f6368", "#008b8b", "#9a7b00"]


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None and isinstance(value, np.ndarray):
        return value.tolist()
    if np is not None and isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def create_console(project_root: str | Path):
    """Build the single Stage 29 PYNQ production console."""
    import ipywidgets as W
    import numpy as np
    import plotly.graph_objects as go

    root = Path(project_root).resolve()
    bitfile = root / "overlay" / "t510_fengine.bit"
    if not bitfile.exists():
        raise FileNotFoundError(bitfile)

    controller = Stage29Controller(bitfile)
    state: dict[str, Any] = {"live": False, "task": None, "last_capture": None}
    label_style = {"description_width": "115px"}
    wide = W.Layout(width="420px")

    bandwidth = W.Dropdown(options=[("100 MHz", 100), ("200 MHz", 200)], value=100, description="Bandwidth", style=label_style, layout=wide)
    mode = W.Dropdown(options=[("TIME only", "time_only"), ("SPEC only", "spec_only"), ("TIME + SPEC", "time_spec")], value="time_spec", description="Mode", style=label_style, layout=wide)
    center_mhz = W.FloatText(value=100.0, description="RF center MHz", style=label_style, layout=wide)
    rust_url = W.Text(value="http://192.168.100.192:8089", description="Rust Web", style=label_style, layout=wide)
    board_id = W.BoundedIntText(value=0, min=0, max=0xFFFF, description="Board ID", style=label_style, layout=wide)
    source_ip = W.Text(value=DEFAULT_SOURCE_IP, description="Source IP", style=label_style, layout=wide)
    source_mac = W.Text(value=DEFAULT_SOURCE_MAC, description="Source MAC", style=label_style, layout=wide)

    def destination_rows(count: int, destination_port_base: int, source_port_base: int) -> list[dict[str, Any]]:
        rows = []
        for flow in range(count):
            rows.append({
                "enabled": W.Checkbox(value=True, indent=False, layout=W.Layout(width="34px")),
                "source": W.HTML(layout=W.Layout(width="315px")),
                "source_port": W.IntText(value=source_port_base + flow, layout=W.Layout(width="92px")),
                "ip": W.Text(value="10.0.1.16", layout=W.Layout(width="145px")),
                "mac": W.Text(value="08:c0:eb:d5:95:b2", layout=W.Layout(width="170px")),
                "port": W.IntText(value=destination_port_base + flow, layout=W.Layout(width="88px")),
            })
        return rows

    time_rows = destination_rows(8, 4300, 4000)
    spec_rows = destination_rows(16, 4308, 4008)

    def destination_table(rows: list[dict[str, Any]], endpoint_base: int) -> W.Widget:
        header = W.HBox([
            W.HTML("<b>On</b>", layout=W.Layout(width="34px")),
            W.HTML("<b>Endpoint</b>", layout=W.Layout(width="68px")),
            W.HTML("<b>Effective source IP / MAC</b>", layout=W.Layout(width="315px")),
            W.HTML("<b>Src port</b>", layout=W.Layout(width="92px")),
            W.HTML("<b>Destination IP</b>", layout=W.Layout(width="145px")),
            W.HTML("<b>Destination MAC</b>", layout=W.Layout(width="170px")),
            W.HTML("<b>Dst port</b>", layout=W.Layout(width="88px")),
        ])
        rendered = [header]
        for flow, row in enumerate(rows):
            rendered.append(W.HBox([
                row["enabled"],
                W.HTML(f"EP{endpoint_base + flow}", layout=W.Layout(width="68px")),
                row["source"], row["source_port"],
                row["ip"], row["mac"], row["port"],
            ]))
        return W.VBox(rendered, layout=W.Layout(overflow_x="auto"))

    def refresh_source_summaries(change: Any = None) -> None:
        effective_ip = escape(str(source_ip.value).strip())
        effective_mac = escape(str(source_mac.value).strip().lower())
        for row in time_rows + spec_rows:
            row["source"].value = f"<code>{effective_ip}</code> / <code>{effective_mac}</code>"

    source_ip.observe(refresh_source_summaries, names="value")
    source_mac.observe(refresh_source_summaries, names="value")
    refresh_source_summaries()

    def bulk_controls(rows: list[dict[str, Any]], destination_base: int, source_base: int) -> W.Widget:
        bulk_ip = W.Text(value="10.0.1.16", description="Bulk IP", style={"description_width": "58px"}, layout=W.Layout(width="250px"))
        bulk_mac = W.Text(value="08:c0:eb:d5:95:b2", description="MAC", style={"description_width": "42px"}, layout=W.Layout(width="260px"))
        bulk_port = W.IntText(value=destination_base, description="Dst base", style={"description_width": "62px"}, layout=W.Layout(width="155px"))
        bulk_source_port = W.IntText(value=source_base, description="Src base", style={"description_width": "62px"}, layout=W.Layout(width="155px"))
        apply_bulk = W.Button(description="Fill table", button_style="info", layout=W.Layout(width="110px"))

        def fill(_button: Any) -> None:
            for flow, row in enumerate(rows):
                row["ip"].value = str(bulk_ip.value).strip()
                row["mac"].value = str(bulk_mac.value).strip()
                row["port"].value = int(bulk_port.value) + flow
                row["source_port"].value = int(bulk_source_port.value) + flow

        apply_bulk.on_click(fill)
        return W.Box(
            [bulk_ip, bulk_mac, bulk_port, bulk_source_port, apply_bulk],
            layout=W.Layout(display="flex", flex_flow="row wrap", align_items="center"),
        )

    dac_rows: list[dict[str, Any]] = []
    for channel in range(8):
        dac_rows.append({
            "enabled": W.Checkbox(value=True, indent=False, layout=W.Layout(width="34px")),
            "frequency": W.FloatText(value=60.010, step=0.001, layout=W.Layout(width="130px")),
            "amplitude": W.FloatSlider(value=25.0, min=0.0, max=100.0, step=0.5, readout_format=".1f", continuous_update=False, layout=W.Layout(width="220px")),
            "phase": W.FloatText(value=0.0, step=1.0, layout=W.Layout(width="105px")),
        })
    dac_header = W.HBox([
        W.HTML("<b>On</b>", layout=W.Layout(width="34px")),
        W.HTML("<b>Lane</b>", layout=W.Layout(width="55px")),
        W.HTML("<b>RF MHz</b>", layout=W.Layout(width="130px")),
        W.HTML("<b>Amplitude %</b>", layout=W.Layout(width="220px")),
        W.HTML("<b>Phase deg</b>", layout=W.Layout(width="105px")),
    ])
    dac_table = W.VBox([dac_header] + [
        W.HBox([row["enabled"], W.HTML(f"CH{channel}", layout=W.Layout(width="55px")), row["frequency"], row["amplitude"], row["phase"]])
        for channel, row in enumerate(dac_rows)
    ], layout=W.Layout(overflow_x="auto"))

    time_window = W.FloatSlider(value=0.25, min=0.05, max=2.0, step=0.05, description="Window us", style=label_style, layout=wide)
    y_scale = W.IntSlider(value=4096, min=256, max=32768, step=256, description="Wave Y codes", style=label_style, layout=wide)
    spectrum_min = W.IntSlider(value=-120, min=-160, max=-20, step=5, description="Spectrum min", style=label_style, layout=wide)
    spectrum_max = W.IntSlider(value=-20, min=-80, max=10, step=5, description="Spectrum max", style=label_style, layout=wide)
    smoothing = W.Checkbox(value=True, description="Smooth spectrum")

    status = W.HTML("<pre>Stage 29 console ready. Apply + Start performs a fresh download.</pre>")
    board_status = W.HTML("<pre>Board not connected.</pre>")
    rust_status = W.HTML("<pre>Rust receiver not queried.</pre>")
    network_status = W.HTML("<pre>Network source/endpoints not applied.</pre>")
    product_status = W.HTML(f"<pre>CORE_VERSION=0x{EXPECTED_CORE_VERSION:08x}; fixed wire/PFB/sync contract.</pre>")

    wave_fig = go.FigureWidget()
    spec_fig = go.FigureWidget()
    for channel in range(8):
        wave_fig.add_trace(go.Scattergl(x=[], y=[], mode="lines", name=f"CH{channel}", line={"color": COLORS[channel], "width": 1.4}))
        spec_fig.add_trace(go.Scattergl(x=[], y=[], mode="lines", name=f"CH{channel}", line={"color": COLORS[channel], "width": 1.4}))
    wave_fig.update_layout(height=360, template="plotly_white", xaxis_title="preview time (us)", yaxis_title="ADC code", title="TIME preview", margin={"l": 58, "r": 20, "t": 42, "b": 46})
    spec_fig.update_layout(height=420, template="plotly_white", xaxis_title="RF frequency (MHz)", yaxis_title="power (dBFS)", title="SPEC preview", margin={"l": 58, "r": 20, "t": 42, "b": 46})
    wave_panel = W.VBox([wave_fig])
    spec_panel = W.VBox([spec_fig])

    def set_status(text: Any, kind: str = "info") -> None:
        color = {"ok": "#0b7a3b", "warn": "#9a6a00", "error": "#b3261e", "info": "#354052"}.get(kind, "#354052")
        status.value = f"<pre style='margin:0;color:{color};white-space:pre-wrap'>{escape(str(text))}</pre>"

    def read_destinations(rows: list[dict[str, Any]]) -> tuple[FlowDestination, ...]:
        return tuple(
            FlowDestination(
                enabled=row["enabled"].value,
                ip=row["ip"].value,
                mac=row["mac"].value,
                destination_port=row["port"].value,
                source_port=row["source_port"].value,
            )
            for row in rows
        )

    def read_dac_channels() -> tuple[DacChannelConfig, ...]:
        return tuple(DacChannelConfig(enabled=row["enabled"].value, rf_frequency_mhz=row["frequency"].value, amplitude=row["amplitude"].value, phase_deg=row["phase"].value) for row in dac_rows)

    def current_config() -> Stage29Config:
        return Stage29Config(
            bandwidth_mhz=int(bandwidth.value), mode=str(mode.value), center_mhz=float(center_mhz.value),
            board_id=int(board_id.value),
            source_ip=str(source_ip.value), source_mac=str(source_mac.value),
            time_destinations=read_destinations(time_rows), spec_destinations=read_destinations(spec_rows),
            dac_channels=read_dac_channels(),
        )

    def update_mode_options(change: Any = None) -> None:
        if int(bandwidth.value) == 200:
            mode.options = [("TIME only", "time_only"), ("SPEC only", "spec_only")]
            if mode.value == "time_spec":
                mode.value = "time_only"
        else:
            mode.options = [("TIME only", "time_only"), ("SPEC only", "spec_only"), ("TIME + SPEC", "time_spec")]

    bandwidth.observe(update_mode_options, names="value")

    def refresh_visibility(config: Stage29Config) -> None:
        wave_panel.layout.display = "" if config.needs_time else "none"
        spec_panel.layout.display = "" if config.needs_spec else "none"

    def compact_board() -> dict[str, Any]:
        core = controller.require_core()
        raw = core.read_status()
        science = core.read_science_output_status()
        pfb = core.read_channelizer_status()
        keys = ("core_version", "board_id", "pps_count", "pps_recent", "time_packet_count", "spec_packet_count", "time_dropped_count", "spec_dropped_count", "science_dropped_beat_count", "tx_route_miss_count", "tx_route_error_count", "pfb_xfft_event_count", "pfb_xfft_tlast_missing_count", "pfb_xfft_tlast_unexpected_count")
        return {
            "board": {key: raw.get(key) for key in keys if key in raw},
            "science": {key: science.get(key) for key in ("science_bandwidth_mhz", "science_output_mode", "time_enabled", "spec_enabled", "science_antialias_100m_active", "science_antialias_100m_primed", "science_block_reasons")},
            "pfb_xfft": {key: pfb.get(key) for key in ("pfb_active", "pfb_taps", "pfb_chan_count", "pfb_time_count", "pfb_coeff_active_valid", "pfb_coeff_error_count")},
        }

    def refresh_board() -> None:
        if controller.core is not None:
            board_status.value = f"<pre style='white-space:pre-wrap'>{escape(json.dumps(_jsonable(compact_board()), indent=2, sort_keys=True))}</pre>"

    def show_network_apply(result: dict[str, Any], config: Stage29Config) -> None:
        source = result.get("source_identity", {})
        endpoints = result.get("endpoint_readback", [])
        rows = []
        for endpoint in endpoints:
            rows.append({
                "endpoint": endpoint.get("id"),
                "enabled": endpoint.get("enable"),
                "source": f"{config.source_ip}:{endpoint.get('src_port')}",
                "source_mac": config.source_mac,
                "destination": f"{endpoint.get('ip')}:{endpoint.get('dst_port')}",
                "destination_mac": endpoint.get("mac"),
            })
        report = {
            "board_identity": result.get("board_identity", {}),
            "source_identity": source,
            "flows": rows,
            "warnings": result.get("flow_warnings", []),
        }
        network_status.value = (
            "<pre style='white-space:pre-wrap'>"
            f"{escape(json.dumps(_jsonable(report), indent=2, sort_keys=True))}</pre>"
        )

    def sync_rust(config: Stage29Config) -> dict[str, Any]:
        base = str(rust_url.value).strip().rstrip("/")
        payload = {
            "bandwidth_mhz": config.bandwidth_mhz,
            "output_mode": config.mode.value,
            "center_mhz": config.center_mhz,
            "expected_mhz": config.target_mhz_by_channel[0],
            "dac_mhz": config.target_mhz_by_channel[0],
            "target_mhz_by_channel": list(config.target_mhz_by_channel),
            "channel_mask": config.dac_enable_mask,
            "phase_deg_by_channel": list(config.phase_deg_by_channel),
            "paused": False,
        }
        request = urllib.request.Request(f"{base}/api/config", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=2.0) as response:
            response.read()
        with urllib.request.urlopen(f"{base}/api/state", timeout=2.0) as response:
            result = json.loads(response.read().decode())
        stats = result.get("stats", {})
        summary = {"flows": [stats.get("time_flow_count"), stats.get("spec_flow_count")], "rates_gbps": [stats.get("rx_processed_gbps"), stats.get("spec_processed_gbps")], "config_generation": result.get("config_generation")}
        rust_status.value = f"<pre>{escape(json.dumps(summary, indent=2))}</pre>"
        return result

    def render_preview(result: dict[str, Any], config: Stage29Config) -> None:
        analysis = result.get("analysis", {})
        channels = analysis.get("channels", analysis.get("inputs", []))
        for channel in range(8):
            row = channels[channel] if channel < len(channels) else {}
            x = row.get("time_us", row.get("x_us", []))
            y = row.get("rf_curve", row.get("rf", row.get("samples", [])))
            wave_fig.data[channel].x = x
            wave_fig.data[channel].y = y
        wave_fig.update_yaxes(range=[-int(y_scale.value), int(y_scale.value)])

        preview = result.get("preview", {})
        raw_channels = preview.get("channels", preview.get("samples", []))
        sample_rate = config.sample_rate_hz
        for channel in range(8):
            values = np.asarray(raw_channels[channel] if channel < len(raw_channels) else [], dtype=np.complex128)
            if values.size:
                spectrum = np.fft.fftshift(np.fft.fft(values, n=4096))
                power = 20.0 * np.log10(np.maximum(np.abs(spectrum), 1.0) / 32768.0)
                if smoothing.value and power.size >= 5:
                    power = np.convolve(power, np.ones(5) / 5.0, mode="same")
                freq = config.center_mhz + np.fft.fftshift(np.fft.fftfreq(4096, d=1.0 / sample_rate)) / 1.0e6
                spec_fig.data[channel].x = freq
                spec_fig.data[channel].y = power
            else:
                spec_fig.data[channel].x = []
                spec_fig.data[channel].y = []
        spec_fig.update_yaxes(range=[int(spectrum_min.value), int(spectrum_max.value)])
        state["last_capture"] = result

    async def capture_once() -> None:
        config = current_config()
        result = await asyncio.to_thread(controller.capture_preview, time_window_us=float(time_window.value))
        render_preview(result, config)
        refresh_board()

    async def live_loop() -> None:
        while state["live"]:
            try:
                await capture_once()
            except Exception as exc:
                set_status(f"Preview error: {exc}", "error")
                state["live"] = False
                break
            await asyncio.sleep(0.5)

    apply_start = W.Button(description="Apply + Start", button_style="success", icon="play")
    apply_dac = W.Button(description="Apply DAC live", button_style="info", icon="bolt")
    stop = W.Button(description="Stop", button_style="danger", icon="stop")
    capture = W.Button(description="Capture once", icon="camera")
    live = W.ToggleButton(description="Live preview", icon="refresh")

    def apply_clicked(_button: Any) -> None:
        try:
            config = current_config()
            set_status("Fresh download and deterministic Stage 29 start in progress…")
            result = controller.apply(config, fresh_download=True)
            refresh_visibility(config)
            show_network_apply(result, config)
            sync_rust(config)
            refresh_board()
            warnings = result.get("flow_warnings", [])
            suffix = f" Warnings: {'; '.join(warnings)}" if warnings else ""
            set_status(
                f"Applied board {config.board_id}, {config.bandwidth_mhz}MHz {config.mode.value}; "
                f"source {config.source_ip} / {config.source_mac}; "
                f"{len(result['endpoints'])} endpoints verified.{suffix}",
                "warn" if warnings else "ok",
            )
        except Exception as exc:
            set_status(f"Apply failed: {exc}", "error")

    def dac_clicked(_button: Any) -> None:
        try:
            result = controller.apply_dac_live(read_dac_channels())
            config = controller.config
            if config is not None:
                sync_rust(config)
            set_status(f"DAC live apply complete; mute {result['mute_duration_us']:.1f} us, mask 0x{result['enable_mask']:02x}.", "ok")
        except Exception as exc:
            set_status(f"DAC live apply failed: {exc}", "error")

    def stop_clicked(_button: Any) -> None:
        state["live"] = False
        live.value = False
        try:
            controller.stop()
            set_status("Science stream stopped.", "warn")
        except Exception as exc:
            set_status(f"Stop failed: {exc}", "error")

    def capture_clicked(_button: Any) -> None:
        asyncio.get_event_loop().create_task(capture_once())

    def live_changed(change: Any) -> None:
        state["live"] = bool(change["new"])
        if state["live"]:
            state["task"] = asyncio.get_event_loop().create_task(live_loop())

    apply_start.on_click(apply_clicked)
    apply_dac.on_click(dac_clicked)
    stop.on_click(stop_clicked)
    capture.on_click(capture_clicked)
    live.observe(live_changed, names="value")

    source_identity = W.VBox([
        W.HTML("<h4 style='margin-bottom:4px'>Board Source Identity</h4>"),
        board_id,
        source_ip,
        source_mac,
        W.HTML("<small>Board ID is written into every T510 packet header. CMAC source IP/MAC are shared by all 24 flows. All three must be unique per board in a multi-board deployment.</small>"),
    ])
    science_tab = W.VBox([bandwidth, mode, center_mhz, rust_url, source_identity, W.HTML("<small>Bandwidth/center/network changes require Apply + Start. Release gates remain in stage29_board_validate.py.</small>")])
    time_tab = W.VBox([bulk_controls(time_rows, 4300, 4000), destination_table(time_rows, 0)])
    spec_tab = W.VBox([bulk_controls(spec_rows, 4308, 4008), destination_table(spec_rows, 8)])
    dac_tab = W.VBox([dac_table, W.HBox([apply_dac]), W.HTML("<small>Live apply briefly mutes DAC only; RFDC and science streaming remain running.</small>")])
    display_tab = W.VBox([time_window, y_scale, spectrum_min, spectrum_max, smoothing])
    tabs = W.Tab(children=[science_tab, time_tab, spec_tab, dac_tab, display_tab])
    for index, title in enumerate(("Science", "TIME receivers", "SPEC receivers", "DAC channels", "Preview")):
        tabs.set_title(index, title)

    controls = W.HBox([apply_start, stop, capture, live])
    health = W.Accordion(children=[product_status, network_status, board_status, rust_status])
    for index, title in enumerate(("Production contract", "Network source / endpoints", "Board / PFB / XFFT / AA100", "Rust receiver")):
        health.set_title(index, title)
    health.selected_index = None
    preview_box = W.VBox([wave_panel, spec_panel])
    return W.VBox([W.HTML("<h2>Stage 29 F-engine Production Control</h2>"), status, controls, tabs, health, preview_box])


__all__ = ["create_console"]
