"""Single-file HTML report. No scripts or external resources, so it opens anywhere."""
from __future__ import annotations

from html import escape

from .inspect_core import FIELDS, GROUPS

CSS = """
:root{color-scheme:light dark;--bg:#f5f6f8;--card:#fff;--text:#1c2128;--muted:#5d6673;--line:#dfe3e8;
--good:#176b3a;--good-bg:#e3f4ea;--warn:#8a5a00;--warn-bg:#fdf1d7;--bad:#a4262c;--bad-bg:#fbe5e6;--na:#59626e;--na-bg:#eceef1;--accent:#3a5bc7}
@media (prefers-color-scheme:dark){:root:not(:has(#t-light:checked)){DARK}}
:root:has(#t-dark:checked){DARK}:root:has(#t-light:checked){color-scheme:light}
.bar{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;font-size:.8rem;color:var(--muted);margin:0 0 18px}
.bar label{cursor:pointer;display:inline-flex;gap:4px;align-items:center}.bar input{margin:0;accent-color:var(--accent)}.bar b{font-weight:600}
td small{display:block;font-size:.75rem;line-height:1.3;color:var(--muted);opacity:.85;margin-top:1px}
body:has(#explain:not(:checked)) td small{display:none}
td:first-child{color:var(--text)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:960px;margin:0 auto;padding:28px 16px 48px}h1{font-size:1.5rem;margin:0}h2{font-size:1.25rem;margin:0 0 4px}
h3{font-size:.8rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
.brand{color:var(--accent);font-weight:600;font-size:.85rem}.meta{color:var(--muted);font-size:.875rem;margin:4px 0 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:16px;break-inside:avoid}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px;margin:14px 0 2px}
.tile{border:1px solid var(--line);border-radius:8px;padding:10px 12px}.tile b{display:block;font-size:1.1rem;overflow-wrap:anywhere}.tile span{font-size:.78rem;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
table{width:100%;border-collapse:collapse;font-size:.875rem}td{padding:5px 0;border-top:1px solid var(--line);vertical-align:top}
tr:first-child td{border-top:0}td:last-child{text-align:right;overflow-wrap:anywhere;padding-left:12px}td:first-child{color:var(--muted)}
.chip{display:inline-block;padding:1px 8px;border-radius:99px;font-size:.75rem;font-weight:600;white-space:nowrap}
.good{color:var(--good);background:var(--good-bg)}.warn{color:var(--warn);background:var(--warn-bg)}.bad{color:var(--bad);background:var(--bad-bg)}.na{color:var(--na);background:var(--na-bg)}
ul{margin:0;padding-left:20px}li{margin:4px 0}.banner{border-left:4px solid var(--bad);background:var(--bad-bg);padding:10px 14px;border-radius:6px;margin-bottom:16px}
footer{color:var(--muted);font-size:.8rem;margin-top:20px}
"""

CSS = CSS.replace("DARK", "color-scheme:dark;--bg:#14171b;--card:#1d2127;--text:#e8eaed;--muted:#a1a9b4;--line:#333942;"
                  "--good:#6fd39a;--good-bg:#17352a;--warn:#e7bd63;--warn-bg:#3b2f13;--bad:#f09a9e;--bad-bg:#44201f;"
                  "--na:#aab2bd;--na-bg:#2a2f36;--accent:#9db2f5")

CONTROLS = """<div class="bar"><b>Theme</b>
<label><input type="radio" name="theme" id="t-auto" checked>Auto</label>
<label><input type="radio" name="theme" id="t-light">Light</label>
<label><input type="radio" name="theme" id="t-dark">Dark</label>
<label><input type="checkbox" id="explain" checked>Explain fields</label></div>"""

EXPLAIN = {
    "name": "The model the card reports.", "uuid": "Nvidia's unique ID for this GPU.", "serial": "Board serial number, if the card has one.",
    "pci_device_id": "Hardware ID for the GPU chip.", "pci_sub_device_id": "Hardware ID that often identifies the board maker.",
    "vbios_version": "Firmware stored on the card.", "driver_version": "The Nvidia driver in use.", "memory_total": "Memory the card reports having.",
    "ecc_mode": "Whether memory error correction is on.", "ecc_corrected_lifetime": "Memory errors fixed over the card's recorded life.",
    "ecc_uncorrected_lifetime": "Memory errors that couldn't be fixed, over its recorded life.",
    "ecc_corrected_since_boot": "Memory errors fixed since the last restart.", "ecc_uncorrected_since_boot": "Memory errors not fixed since the last restart.",
    "retired_pages_single_bit": "Memory pages retired after repeated fixable errors.", "retired_pages_double_bit": "Memory pages retired after unfixable errors.",
    "retired_pages_pending": "A page will be retired at the next restart.", "remapped_rows_correctable": "Memory rows replaced after fixable errors.",
    "remapped_rows_uncorrectable": "Memory rows replaced after unfixable errors.", "remapped_rows_pending": "A row will be replaced at the next reset.",
    "remapped_rows_failure": "The card failed to replace a memory row.", "pcie_gen_current": "Link speed generation in use now. It may drop at idle.",
    "pcie_gen_max": "Fastest link generation available to the card.", "pcie_width_current": "Link lanes in use now.", "pcie_width_max": "Most link lanes available to the card.",
    "power_draw": "Power the card is using now.", "power_limit": "Power cap currently set.", "power_max_limit": "Highest power cap allowed.",
    "temperature_gpu": "GPU chip temperature now.", "temperature_memory": "Memory temperature now, if the card has a sensor.",
    "fan_speed": "Fan speed the card reports.", "pstate": "P0 is highest performance. Higher numbers use less power.",
    "clock_graphics": "GPU chip speed now.", "clock_memory": "Memory speed now.", "slowdown_sw_power_cap": "The driver is holding speed to the power limit.",
    "slowdown_hw": "The hardware is slowing itself for any reason.", "slowdown_hw_thermal": "The hardware is slowing itself because of heat.",
    "slowdown_hw_power_brake": "An external power signal is slowing the card.", "slowdown_sw_thermal": "The driver is slowing the card because of heat.",
}

LABELS = {
    "name": "Name", "uuid": "GPU UUID", "serial": "Serial", "pci_device_id": "PCI device ID", "pci_sub_device_id": "PCI sub-device ID",
    "vbios_version": "VBIOS", "driver_version": "Driver", "memory_total": "Total VRAM", "ecc_mode": "ECC mode",
    "ecc_corrected_lifetime": "Corrected ECC, lifetime", "ecc_uncorrected_lifetime": "Uncorrected ECC, lifetime",
    "ecc_corrected_since_boot": "Corrected ECC, since boot", "ecc_uncorrected_since_boot": "Uncorrected ECC, since boot",
    "retired_pages_single_bit": "Retired pages, single-bit", "retired_pages_double_bit": "Retired pages, double-bit",
    "retired_pages_pending": "Page retirement pending", "remapped_rows_correctable": "Remapped rows, correctable",
    "remapped_rows_uncorrectable": "Remapped rows, uncorrectable", "remapped_rows_pending": "Row remap pending",
    "remapped_rows_failure": "Row remap failure", "pcie_gen_current": "PCIe generation, now", "pcie_gen_max": "PCIe generation, max",
    "pcie_width_current": "PCIe width, now", "pcie_width_max": "PCIe width, max", "power_draw": "Power draw", "power_limit": "Power limit",
    "power_max_limit": "Max power limit", "temperature_gpu": "GPU temperature", "temperature_memory": "Memory temperature",
    "fan_speed": "Fan speed", "pstate": "Performance state", "clock_graphics": "Graphics clock", "clock_memory": "Memory clock",
    "slowdown_sw_power_cap": "Software power cap", "slowdown_hw": "Hardware slowdown", "slowdown_hw_thermal": "Hardware thermal slowdown",
    "slowdown_hw_power_brake": "Power brake slowdown", "slowdown_sw_thermal": "Software thermal slowdown",
}
STATUS_TEXT = {
    "not_available": "not available", "unsupported": "not supported", "permission_denied": "permission denied", "read_error": "read error",
    "parse_error": "could not parse", "unknown_to_driver": "unknown to driver", "redacted": "redacted",
}


def _chip(text: str, kind: str) -> str:
    return f'<span class="chip {kind}">{escape(text)}</span>'


def _fmt(n) -> str:
    return f"{n:g}" if isinstance(n, float) else str(n)


def _value(f: dict) -> str:
    if f["status"] != "value":
        kind = "bad" if f["status"] in {"read_error", "parse_error", "permission_denied"} else "na"
        return _chip(STATUS_TEXT.get(f["status"], f["status"]), kind)
    v = _fmt(f["value"]) + (f" {f['unit']}" if f["unit"] and f["unit"] != "%" else (f["unit"] or ""))
    if v == "Active":
        return _chip("Active", "warn")
    if v == "Not Active":
        return _chip("Not active", "good")
    return escape(v)


def _tile(label: str, value: str) -> str:
    return f'<div class="tile"><b>{value}</b><span>{escape(label)}</span></div>'


def _plain(f: dict) -> str:
    if f["status"] != "value":
        return escape(STATUS_TEXT.get(f["status"], f["status"]).capitalize())
    return escape(_fmt(f["value"]) + (f" {f['unit']}" if f["unit"] and f["unit"] != "%" else (f["unit"] or "")))


def _checks(title: str, checks: list[dict]) -> str:
    kinds = {"match": "good", "mismatch": "bad", "not_compared": "na"}
    rows = "".join(f"<tr><td>{escape(LABELS.get(c['field'], c['field']))}</td><td>{_chip(c['result'].replace('_', ' '), kinds[c['result']])}</td></tr>" for c in checks)
    return f'<div class="card"><h3>{escape(title)}</h3><table>{rows}</table></div>'


def _gpu(g: dict) -> str:
    f, d = g["fields"], g["details"]
    width = f["pcie_width_current"]
    gen = f["pcie_gen_current"]
    link = f"PCIe {gen['value']}.0 x{width['value']}" if gen["status"] == width["status"] == "value" else "Unknown"
    tiles = [
        _tile("Total VRAM", _plain(f["memory_total"])), _tile("Architecture", escape(d.get("architecture") or "Unknown")),
        _tile("GPU temperature", _plain(f["temperature_gpu"])), _tile("Power draw", _plain(f["power_draw"])),
        _tile("Fan speed", _plain(f["fan_speed"])), _tile("PCIe link now", escape(link)),
        _tile("Slowdown limit", f"{_fmt(d['slowdown_temp'])} C" if d.get("slowdown_temp") else "Unknown"),
    ]
    head = f'<div class="card"><h2>GPU {g["index"]}: {escape(str(f["name"]["value"]))}</h2><div class="tiles">{"".join(tiles)}</div></div>'
    cards = []
    for title, group in GROUPS:
        rows = "".join(f"<tr><td>{escape(LABELS[k])}<small>{escape(EXPLAIN[k])}</small></td><td>{_value(f[k])}</td></tr>" for k, grp, *_ in FIELDS if grp == group)
        cards.append(f'<div class="card"><h3>{escape(title)}</h3><table>{rows}</table></div>')
    cards.append(_checks("Cross-check: query vs XML", g["crosschecks"]))
    nv = g["nvml_crosscheck"]
    if nv["status"] == "run":
        cards.append(_checks("Cross-check: query vs NVML", nv["checks"]))
    else:
        cards.append(f'<div class="card"><h3>Cross-check: query vs NVML</h3>{_chip(nv["status"].replace("_", " "), "na")} {escape(nv["reason"])}</div>')
    notes = "".join(f"<li>{escape(n)}</li>" for n in g["notes"])
    return head + f'<div class="grid">{"".join(cards)}</div><div class="card"><h3>Notes</h3><ul>{notes}</ul></div>'


def to_html(report: dict) -> str:
    env = report.get("environment", "unknown")
    meta = " &middot; ".join(escape(str(x)) for x in (
        report.get("collected_at", "Time unknown"), f"Mode: {report['mode']}", f"Environment: {env}",
        f"Driver {report.get('driver_version') or 'unknown'}", f"CUDA reported by driver: {report.get('cuda_version') or 'unknown'}",
        f"GPUDoc {report.get('tool_version', 'unknown')}"))
    state = _chip("Complete", "good") if report["complete"] else _chip("Incomplete", "bad")
    redacted = " " + _chip("Redacted", "na") if report.get("redacted") else ""
    errors = ""
    if report["errors"]:
        errors = '<div class="banner"><strong>Errors while collecting</strong><ul>' + "".join(f"<li>{escape(e)}</li>" for e in report["errors"]) + "</ul></div>"
    gpus = "".join(_gpu(g) for g in report["gpus"]) or '<div class="card">No GPU data was collected.</div>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GPUDoc inspection</title><style>{CSS}</style></head><body><main>
<div class="brand">GPUDoc</div><h1>GPU inspection {state}{redacted}</h1><p class="meta">{meta}</p>{CONTROLS}{errors}{gpus}
<footer>This report shows what the driver reported at one moment. It is not a health verdict, and inspection does not stress the card.</footer>
</main></body></html>"""
