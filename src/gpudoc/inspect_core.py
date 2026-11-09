"""Read-only GPU inspection: collect, cross-check, and report."""
from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "gpudoc.inspect/1"

# key, group, candidate nvidia-smi names (newest first), kind, unit
FIELDS = [
    ("name", "identity", ["name"], "str", None),
    ("uuid", "identity", ["uuid", "gpu_uuid"], "str", None),
    ("serial", "identity", ["serial", "gpu_serial"], "str", None),
    ("pci_device_id", "identity", ["pci.device_id"], "str", None),
    ("pci_sub_device_id", "identity", ["pci.sub_device_id"], "str", None),
    ("vbios_version", "identity", ["vbios_version"], "str", None),
    ("driver_version", "software", ["driver_version"], "str", None),
    ("memory_total", "memory", ["memory.total"], "float", "MiB"),
    ("ecc_mode", "memory_health", ["ecc.mode.current"], "str", None),
    ("ecc_corrected_lifetime", "memory_health", ["ecc.errors.corrected.aggregate.total"], "int", None),
    ("ecc_uncorrected_lifetime", "memory_health", ["ecc.errors.uncorrected.aggregate.total"], "int", None),
    ("ecc_corrected_since_boot", "memory_health", ["ecc.errors.corrected.volatile.total"], "int", None),
    ("ecc_uncorrected_since_boot", "memory_health", ["ecc.errors.uncorrected.volatile.total"], "int", None),
    ("retired_pages_single_bit", "memory_health", ["retired_pages.sbe", "retired_pages.single_bit_ecc.count"], "int", None),
    ("retired_pages_double_bit", "memory_health", ["retired_pages.dbe", "retired_pages.double_bit.count"], "int", None),
    ("retired_pages_pending", "memory_health", ["retired_pages.pending"], "str", None),
    ("remapped_rows_correctable", "memory_health", ["remapped_rows.correctable", "remapped_rows.sbe"], "int", None),
    ("remapped_rows_uncorrectable", "memory_health", ["remapped_rows.uncorrectable", "remapped_rows.dbe"], "int", None),
    ("remapped_rows_pending", "memory_health", ["remapped_rows.pending"], "str", None),
    ("remapped_rows_failure", "memory_health", ["remapped_rows.failure"], "str", None),
    ("pcie_gen_current", "pcie", ["pcie.link.gen.current"], "int", None),
    ("pcie_gen_max", "pcie", ["pcie.link.gen.max"], "int", None),
    ("pcie_width_current", "pcie", ["pcie.link.width.current"], "int", None),
    ("pcie_width_max", "pcie", ["pcie.link.width.max"], "int", None),
    ("power_draw", "power_thermal", ["power.draw"], "float", "W"),
    ("power_limit", "power_thermal", ["power.limit"], "float", "W"),
    ("power_max_limit", "power_thermal", ["power.max_limit"], "float", "W"),
    ("temperature_gpu", "power_thermal", ["temperature.gpu"], "int", "C"),
    ("temperature_memory", "power_thermal", ["temperature.memory"], "int", "C"),
    ("fan_speed", "power_thermal", ["fan.speed"], "int", "%"),
    ("pstate", "activity", ["pstate"], "str", None),
    ("clock_graphics", "activity", ["clocks.current.graphics"], "int", "MHz"),
    ("clock_memory", "activity", ["clocks.current.memory"], "int", "MHz"),
    ("slowdown_sw_power_cap", "throttle", ["clocks_event_reasons.sw_power_cap", "clocks_throttle_reasons.sw_power_cap"], "str", None),
    ("slowdown_hw", "throttle", ["clocks_event_reasons.hw_slowdown", "clocks_throttle_reasons.hw_slowdown"], "str", None),
    ("slowdown_hw_thermal", "throttle", ["clocks_event_reasons.hw_thermal_slowdown", "clocks_throttle_reasons.hw_thermal_slowdown"], "str", None),
    ("slowdown_hw_power_brake", "throttle", ["clocks_event_reasons.hw_power_brake_slowdown", "clocks_throttle_reasons.hw_power_brake_slowdown"], "str", None),
    ("slowdown_sw_thermal", "throttle", ["clocks_event_reasons.sw_thermal_slowdown", "clocks_throttle_reasons.sw_thermal_slowdown"], "str", None),
]

PRIVATE_FIELDS = {"uuid", "serial"}

# Maps nvidia-smi placeholders to a status. A placeholder never becomes zero.
PLACEHOLDERS = {
    "[n/a]": "not_available",
    "n/a": "not_available",
    "[not supported]": "unsupported",
    "[insufficient permissions]": "permission_denied",
}

LEGACY_ARCHITECTURES = {"Maxwell", "Pascal", "Volta"}


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str = ""


class LocalRunner:
    mode = "local"

    def nvml(self):
        from .nvml import read_nvml
        return read_nvml()

    def run(self, args: list[str]) -> Result:
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=60)
        except FileNotFoundError as e:
            return Result(127, "", str(e))
        except subprocess.TimeoutExpired:
            return Result(124, "", "timed out")
        return Result(p.returncode, p.stdout, p.stderr)


class SshRunner:
    mode = "ssh"

    def __init__(self, target: str):
        self.target = target

    def nvml(self):
        return None  # NVML is only readable on the GPU's own machine.

    def run(self, args: list[str]) -> Result:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", self.target, " ".join(args)]
        return LocalRunner().run(cmd)


class CaptureRunner:
    """Replays real saved output for tests and re-parsing."""

    mode = "capture"
    files = {"--help-query-gpu": "help_query_gpu.txt", "-x": "q_x.xml"}

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def nvml(self):
        path = self.folder / "nvml.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def run(self, args: list[str]) -> Result:
        name = "query_gpu.csv"
        for flag, f in self.files.items():
            if flag in args:
                name = f
        path = self.folder / name
        if not path.exists():
            return Result(1, "", f"capture missing: {name}")
        return Result(0, path.read_text(encoding="utf-8"))


def parse_valid_fields(help_text: str) -> set[str]:
    names: set[str] = set()
    for line in help_text.splitlines():
        if line.startswith('"'):
            names.update(re.findall(r'"([^"]+)"', line))
    return names


def resolve_fields(valid: set[str]) -> dict[str, str | None]:
    return {key: next((c for c in cands if c in valid), None) for key, _, cands, _, _ in FIELDS}


def parse_cell(raw: str, kind: str) -> tuple[str, object]:
    text = raw.strip()
    low = text.lower()
    if low in PLACEHOLDERS:
        return PLACEHOLDERS[low], None
    if text.startswith("[") and text.endswith("]"):
        return "read_error", None
    if kind == "str":
        return "value", text
    try:
        return "value", int(text) if kind == "int" else float(text)
    except ValueError:
        return "parse_error", None


def parse_query_csv(text: str, keys: list[str]) -> list[dict[str, str]]:
    rows = []
    for row in csv.reader(io.StringIO(text), skipinitialspace=True):
        if row:
            if len(row) != len(keys):
                raise ValueError(f"expected {len(keys)} columns, got {len(row)}")
            rows.append(dict(zip(keys, row)))
    return rows


def _number(text: str | None):
    m = re.match(r"\s*(\d+(?:\.\d+)?)", text or "")
    return float(m.group(1)) if m else None


def parse_xml(text: str) -> dict:
    root = ET.fromstring(text)
    out = {"driver_version": root.findtext("driver_version"), "cuda_version": root.findtext("cuda_version"), "gpus": []}
    for g in root.findall("gpu"):
        t = lambda path: g.findtext(path)
        out["gpus"].append({
            "name": t("product_name"), "brand": t("product_brand"), "architecture": t("product_architecture"),
            "uuid": t("uuid"), "vbios_version": t("vbios_version"), "gpu_part_number": t("gpu_part_number"),
            "inforom_image": t("inforom_version/img_version"), "pci_bus_id": t("pci/pci_bus_id"),
            "display_active": t("display_active"), "replay_counter": t("pci/replay_counter"),
            "pcie_gen_max": _number(t("pci/pci_gpu_link_info/pcie_gen/max_link_gen")),
            "pcie_width_max": _number(t("pci/pci_gpu_link_info/link_widths/max_link_width")),
            "memory_total": _number(t("fb_memory_usage/total")),
            "slowdown_temp": _number(t("temperature/gpu_temp_slow_threshold")),
            "shutdown_temp": _number(t("temperature/gpu_temp_max_threshold")),
            # Shown as "GPU Max Operating Temp" in nvidia-smi -q. Reads N/A on the GTX 1060 with driver 580.178.04.
            "max_operating_temp": _number(t("temperature/gpu_temp_max_gpu_threshold")),
            "target_temp": _number(t("temperature/gpu_target_temperature")),
        })
    return out


def _field(status, value, unit, source, raw=None):
    item = {"status": status, "value": value, "unit": unit, "source": source}
    if status != "value" and raw is not None:
        item["raw"] = raw
    return item


def _notes(g: dict, xml: dict) -> list[str]:
    f, notes = g["fields"], []
    if f["ecc_uncorrected_lifetime"]["status"] != "value":
        notes.append("ECC history is not available on this card. A memory pattern test is needed for memory evidence.")
    else:
        v = f["ecc_uncorrected_lifetime"]["value"]
        if v:
            notes.append(f"The card reports {v} lifetime uncorrected ECC errors. Review with a load test.")
        else:
            notes.append("Lifetime uncorrected ECC count is zero. Counters may have been cleared, so this alone does not prove clean history.")
    for key, label in (("retired_pages_pending", "page retirement"), ("remapped_rows_pending", "row remap")):
        if f[key]["status"] == "value" and str(f[key]["value"]).lower() in {"yes", "1"}:
            notes.append(f"A pending {label} was reported. Reboot and inspect again.")
    if xml.get("architecture") in LEGACY_ARCHITECTURES:
        notes.append(f"{xml['architecture']} is in the group reported to end at driver branch R580 and CUDA Toolkit 12.9 for builds. Confirm on Nvidia's pages.")
    cur, mx = f["pcie_width_current"], f["pcie_width_max"]
    if cur["status"] == mx["status"] == "value" and cur["value"] < mx["value"]:
        notes.append(f"The PCIe link is x{cur['value']}, and the card supports x{mx['value']}. Slots, risers and adapters often limit "
                     "width, so this alone doesn't point to a fault in the card. Check the slot's rated width in the motherboard's specs.")
    notes.append("Inspection does not stress the card, so it cannot show how the card behaves under load.")
    return notes


def _crosscheck(fields: dict, xml: dict, driver: str | None) -> list[dict]:
    checks = []
    pairs = [("name", xml.get("name")), ("vbios_version", xml.get("vbios_version")), ("uuid", xml.get("uuid")),
             ("driver_version", driver), ("memory_total", xml.get("memory_total")),
             ("pcie_gen_max", xml.get("pcie_gen_max")), ("pcie_width_max", xml.get("pcie_width_max"))]
    for key, other in pairs:
        a = fields[key]
        if a["status"] != "value" or other is None:
            checks.append({"field": key, "result": "not_compared"})
        elif isinstance(a["value"], (int, float)):
            checks.append({"field": key, "result": "match" if float(a["value"]) == float(other) else "mismatch"})
        else:
            checks.append({"field": key, "result": "match" if str(a["value"]) == str(other) else "mismatch"})
    return checks


def _nvml_crosscheck(fields: dict, nv: dict | None, nv_gpu: dict | None) -> dict:
    if nv is None:
        return {"status": "not_run", "reason": "NVML is only read on the GPU's own machine"}
    if "error" in nv:
        return {"status": "error", "reason": nv["error"]}
    if nv_gpu is None:
        return {"status": "error", "reason": "NVML did not report this GPU"}
    merged = dict(nv_gpu, driver_version=nv.get("driver_version"))
    return {"status": "run", "checks": _crosscheck(fields, merged, merged["driver_version"])}


def inspect(runner) -> tuple[dict, dict[str, str]]:
    """Returns the report and the raw command output to save."""
    raw: dict[str, str] = {}
    report = {"schema": SCHEMA, "mode": runner.mode, "commands": [], "gpus": [], "errors": []}

    def call(label, args, file):
        r = runner.run(args)
        report["commands"].append({"name": label, "args": args, "returncode": r.returncode})
        if r.stdout:
            raw[file] = r.stdout
        if r.returncode != 0:
            report["errors"].append(f"{label} failed with code {r.returncode}: {r.stderr.strip()[:300]}")
        return r if r.returncode == 0 else None

    h = call("list_fields", ["nvidia-smi", "--help-query-gpu"], "help_query_gpu.txt")
    if not h:
        report["complete"] = False
        return report, raw
    mapping = resolve_fields(parse_valid_fields(h.stdout))
    keys = [k for k, v in mapping.items() if v]
    q = call("query", ["nvidia-smi", f"--query-gpu={','.join(mapping[k] for k in keys)}", "--format=csv,noheader,nounits"], "query_gpu.csv")
    x = call("xml", ["nvidia-smi", "-q", "-x"], "q_x.xml")
    xml = {"gpus": []}
    if x:
        try:
            xml = parse_xml(x.stdout)
        except ET.ParseError as e:
            report["errors"].append(f"xml could not be parsed: {e}")
    nv = runner.nvml()
    if nv is not None:
        raw["nvml.json"] = json.dumps(nv, indent=2)
    report["driver_version"] = xml.get("driver_version")
    report["cuda_version"] = xml.get("cuda_version")
    rows = []
    if q:
        try:
            rows = parse_query_csv(q.stdout, keys)
        except ValueError as e:
            report["errors"].append(f"query could not be parsed: {e}")
    for i, row in enumerate(rows):
        fields = {}
        for key, group, _, kind, unit in FIELDS:
            if mapping[key] is None:
                fields[key] = _field("unknown_to_driver", None, unit, "none")
            else:
                status, value = parse_cell(row[key], kind)
                fields[key] = _field(status, value, unit, "nvidia-smi query", row[key].strip())
        x_gpu = xml["gpus"][i] if i < len(xml["gpus"]) else {}
        gpu = {"index": i, "fields": fields, "details": {k: v for k, v in x_gpu.items() if k != "uuid"}}
        gpu["crosschecks"] = _crosscheck(fields, x_gpu, xml.get("driver_version"))
        nv_gpus = (nv or {}).get("gpus", [])
        gpu["nvml_crosscheck"] = _nvml_crosscheck(fields, nv, nv_gpus[i] if i < len(nv_gpus) else None)
        gpu["notes"] = _notes(gpu, x_gpu)
        report["gpus"].append(gpu)
    report["complete"] = bool(rows) and x is not None and not report["errors"]
    return report, raw


def redact(report: dict) -> dict:
    import copy
    out = copy.deepcopy(report)
    out.pop("host", None)
    for c in out["commands"]:
        c.pop("args", None)
    for g in out["gpus"]:
        for key in PRIVATE_FIELDS:
            f = g["fields"][key]
            f.update(status="redacted", value=None)
            f.pop("raw", None)
        g["details"].pop("pci_bus_id", None)
    out["redacted"] = True
    return out


GROUPS = [("Identity", "identity"), ("Software", "software"), ("Memory", "memory"), ("Memory health", "memory_health"),
          ("PCIe", "pcie"), ("Power and temperature", "power_thermal"), ("Activity", "activity"), ("Slowdown flags", "throttle")]


def to_markdown(report: dict) -> str:
    lines = ["# GPUDoc inspection", "", f"- **Collected:** {report.get('collected_at', 'unknown')}",
             f"- **Tool:** {report.get('tool_version', 'unknown')}", f"- **Mode:** {report['mode']}", f"- **Environment:** {report.get('environment', 'unknown')}",
             f"- **Complete:** {'yes' if report['complete'] else 'NO'}",
             f"- **Driver:** {report.get('driver_version') or 'unknown'}; **CUDA reported by driver:** {report.get('cuda_version') or 'unknown'}"]
    if report.get("redacted"):
        lines.append("- **Redacted:** identifiers and machine details removed")
    lines.append("")
    if report["errors"]:
        lines += ["## Errors", ""] + [f"- {e}" for e in report["errors"]] + [""]
    if not report["gpus"]:
        lines += ["No GPU data was collected.", ""]
    for g in report["gpus"]:
        d = g["details"]
        lines += [f"## GPU {g['index']}: {g['fields']['name']['value']}", "",
                  f"Architecture: {d.get('architecture') or 'unknown'}. Slowdown limit: {d.get('slowdown_temp') or 'unknown'} C. "
                  f"Shutdown limit: {d.get('shutdown_temp') or 'unknown'} C.", ""]
        for title, group in GROUPS:
            lines += [f"### {title}", "", "| Field | Status | Value |", "|---|---|---|"]
            for key, grp, _, _, unit in FIELDS:
                if grp == group:
                    f = g["fields"][key]
                    val = "" if f["value"] is None else f"{f['value']}{' ' + unit if unit else ''}"
                    lines.append(f"| {key} | {f['status']} | {val} |")
            lines.append("")
        lines += ["### Cross-checks: query vs XML", ""] + [f"- {c['field']}: {c['result']}" for c in g["crosschecks"]] + [""]
        nv = g["nvml_crosscheck"]
        lines += ["### Cross-checks: query vs NVML", ""]
        if nv["status"] == "run":
            lines += [f"- {c['field']}: {c['result']}" for c in nv["checks"]] + [""]
        else:
            lines += [f"- {nv['status']}: {nv['reason']}", ""]
        lines += ["### Notes", ""] + [f"- {n}" for n in g["notes"]] + [""]
    lines += ["This report shows what the driver reported at one moment. It is not a health verdict.", ""]
    return "\n".join(lines)
