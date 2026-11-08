"""Phase 2 draft: run a stress tool with live monitoring, safety stops, and strict result rules.

A run can only PASS when the tool prints its exact completion line, the tool is confirmed
stopped, and no rule found a problem. An exit code alone never decides a result.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .inspect_core import LocalRunner, inspect, parse_cell

SAMPLE_FIELDS = [
    ("temperature_gpu", "temperature.gpu", "int"), ("fan_speed", "fan.speed", "int"), ("power_draw", "power.draw", "float"),
    ("gpu_util", "utilization.gpu", "int"), ("memory_used", "memory.used", "int"), ("pstate", "pstate", "str"),
    ("hw_thermal", "clocks_event_reasons.hw_thermal_slowdown", "str"), ("sw_thermal", "clocks_event_reasons.sw_thermal_slowdown", "str"),
    ("sw_power_cap", "clocks_event_reasons.sw_power_cap", "str"), ("driver_version", "driver_version", "str"),
]
OLD_NAMES = {"clocks_event_reasons": "clocks_throttle_reasons"}
DEFAULT_TEMP_LIMIT = 85
SLOWDOWN_MARGIN = 5


# ---------- memtest_vulkan adapter ----------
class MemtestVulkan:
    """Adapter for memtest_vulkan v0.5.0, whose output format was read from real runs."""

    id = "memtest_vulkan"
    version = "0.5.0"
    reports_device = True
    COMPLETE = "Standard 5-minute test PASSed!"
    PROGRESS = re.compile(r"^\s*(\d+) iteration\. Passed\s+[\d.]+ seconds")
    # Real line: "Standard 5-minute test of 1: Bus=0x01:00 DevId=0x1C03   6GB NVIDIA GeForce GTX 1060 6GB"
    TESTED = re.compile(r"Standard 5-minute test of (\d+): Bus=0x([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}) DevId=0x([0-9A-Fa-f]{4})")
    # No real failing log exists yet, so this match is unverified. A match can only make a run fail.
    FAILURE = re.compile(r"\b(FAIL|Error|ERROR|error)\b")

    def __init__(self, exe: str, device_label: int | None = None):
        self.exe, self.device_label = exe, device_label

    def command(self) -> list[str]:
        # A device number as the first argument skips the selection menu. This comes from the project's
        # main-branch source, not a v0.5.0 test, so the device the tool reports is checked during the run.
        return [self.exe] + ([str(self.device_label)] if self.device_label is not None else [])

    def parse(self, text: str) -> dict:
        lines = text.splitlines()
        tested = next((m for m in map(self.TESTED.search, lines) if m), None)
        return {
            "completed": any(line.strip().startswith(self.COMPLETE) for line in lines),
            "failure_lines": [line.strip() for line in lines if self.FAILURE.search(line)][:20],
            "iterations": max((int(m.group(1)) for m in map(self.PROGRESS.match, lines) if m), default=0),
            "started": any("Standard 5-minute test of" in line for line in lines),
            "tested_device": {"label": int(tested.group(1)), "bus": int(tested.group(2), 16), "device": int(tested.group(3), 16),
                              "dev_id": int(tested.group(4), 16)} if tested else None,
        }


def memtest_label_for(gpus: list[dict], target: dict) -> int | None:
    """memtest_vulkan's 1-based device number for a card, assuming its main-branch order: discrete GPUs
    first, then highest PCI bus first. That order is unverified on v0.5.0, so the run checks the
    device the tool reports and stops if it's the wrong card."""
    keyed = [(parse_bus_id(g["details"].get("pci_bus_id")), g) for g in gpus]
    if any(k is None for k, _ in keyed):
        return None
    order = sorted(keyed, key=lambda kg: kg[0][1], reverse=True)
    return next(i + 1 for i, (_, g) in enumerate(order) if g is target)


class LlamaBench:
    """Adapter for llama-bench JSONL output, read from real b12177 Vulkan runs."""

    id = "llama_bench"
    version = "llama.cpp build reported in results"
    stdout_only = True

    def __init__(self, exe: str, model: str, repetitions: int = 3):
        self.exe, self.model, self.repetitions = exe, model, repetitions

    def command(self) -> list[str]:
        return [self.exe, "-m", self.model, "-ngl", "99", "-p", "512", "-n", "256", "-r", str(self.repetitions), "-o", "jsonl"]

    def parse(self, text: str) -> dict:
        rows = []
        for line in text.splitlines():
            if line.startswith("{"):
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        prompt = [r for r in rows if r.get("n_prompt") and not r.get("n_gen")]
        gen = [r for r in rows if r.get("n_gen") and not r.get("n_prompt")]
        return {
            "completed": bool(prompt) and bool(gen), "failure_lines": [], "iterations": len(rows), "started": bool(rows),
            "prompt_tokens_per_second": prompt[-1].get("avg_ts") if prompt else None,
            "generation_tokens_per_second": gen[-1].get("avg_ts") if gen else None,
            "backend": rows[-1].get("backends") if rows else None, "gpu_layers": rows[-1].get("n_gpu_layers") if rows else None,
        }


# ---------- GPU selection ----------
BUS_ID = re.compile(r"^(?:([0-9A-Fa-f]{1,8}):)?([0-9A-Fa-f]{1,2}):([0-9A-Fa-f]{1,2})\.([0-7])$")


def parse_bus_id(text: str | None) -> tuple[int, int, int, int] | None:
    """Reads a PCI bus ID such as 00000000:02:00.0 or 02:00.0 into (domain, bus, device, function)."""
    m = BUS_ID.match((text or "").strip())
    if not m:
        return None
    return int(m.group(1) or "0", 16), int(m.group(2), 16), int(m.group(3), 16), int(m.group(4))


def describe_gpu(g: dict) -> str:
    return f"GPU {g['index']}: {g['fields']['name']['value']} at {g['details'].get('pci_bus_id') or 'unknown bus'}"


def select_gpu(report: dict, wanted: str | None) -> tuple[dict | None, str | None]:
    """Finds the card to test by nvidia-smi index or PCI bus ID. Returns (gpu, None) or (None, reason)."""
    gpus = report["gpus"]
    if not gpus:
        return None, "No GPU was detected."
    listing = "; ".join(describe_gpu(g) for g in gpus)
    if wanted is None:
        if len(gpus) == 1:
            return gpus[0], None
        return None, f"{len(gpus)} GPUs are installed, so choose one with --gpu, by index or PCI bus ID. Found: {listing}."
    wanted = wanted.strip()
    if wanted.isdigit():
        match = [g for g in gpus if g["index"] == int(wanted)]
    else:
        want = parse_bus_id(wanted)
        if want is None:
            return None, f"'{wanted}' isn't a GPU index or a PCI bus ID such as 02:00.0. Found: {listing}."
        match = [g for g in gpus if parse_bus_id(g["details"].get("pci_bus_id")) == want]
    if not match:
        return None, f"No GPU matches '{wanted}'. Found: {listing}."
    g = match[0]
    if len(gpus) > 1:
        # The query rows and XML entries are paired by position. With several cards, only trust the pairing when the UUIDs agree.
        uuid = next((c["result"] for c in g["crosschecks"] if c["field"] == "uuid"), None)
        if uuid != "match":
            return None, f"Couldn't confirm which bus {describe_gpu(g)} is on, because nvidia-smi's two outputs don't agree on its UUID."
    return g, None


def device_check(tested: dict | None, g: dict, gpu_count: int) -> dict | None:
    """Compares the device a tool says it tested with the selected card. Returns a finding, or None if it matches."""
    if tested is None:
        if gpu_count > 1:
            return {"rule": "RUN-009", "state": "INCONCLUSIVE", "text": "The tool didn't say which card it tested, and more than one GPU is installed."}
        return None
    bus = parse_bus_id(g["details"].get("pci_bus_id"))
    dev = g["fields"]["pci_device_id"]["value"]
    dev_id = int(dev, 16) >> 16 if dev else None
    if bus is None or dev_id is None:
        return {"rule": "RUN-009", "state": "INCONCLUSIVE", "text": "The selected card's bus or device ID is unknown, so the tested card can't be confirmed."}
    if (tested["bus"], tested["device"], tested["dev_id"]) != (bus[1], bus[2], dev_id):
        return {"rule": "RUN-008", "state": "INCONCLUSIVE", "text": (
            f"The tool tested Bus=0x{tested['bus']:02X}:{tested['device']:02X} DevId=0x{tested['dev_id']:04X}, "
            f"not the selected {describe_gpu(g)}. The result doesn't apply to the selected card.")}
    return None


def combine(results: list[dict]) -> str:
    """A suite is only as good as its weakest step. An empty suite proves nothing."""
    states = {r["state"] for r in results}
    return next((s for s in ("FAIL", "INCONCLUSIVE", "ATTENTION") if s in states), "PASS" if results else "INCONCLUSIVE")


# ---------- process control ----------
def stop_and_confirm(proc: subprocess.Popen, timeout: float = 30.0) -> dict:
    """Stops a process and confirms it exited. An unconfirmed stop must be reported."""
    if proc.poll() is not None:
        return {"stopped": True, "method": "already_exited", "exit_code": proc.returncode}
    # memtest_vulkan appears to run a separate worker that outlives its parent, so stop the whole tree.
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=timeout)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
    try:
        proc.wait(timeout=timeout)
        return {"stopped": True, "method": "tree_killed", "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"stopped": False, "method": "kill_timed_out", "exit_code": None}


def still_running(pattern: str, runner) -> list[str]:
    """Lists matching processes, because a dead parent doesn't prove its workers stopped."""
    if os.name == "nt":
        r = runner.run(["tasklist", "/FO", "CSV", "/NH"])
    else:
        r = runner.run(["ps", "-eo", "comm"])
    return [line for line in r.stdout.splitlines() if pattern.lower() in line.lower()]


# ---------- telemetry ----------
def resolve_sample_fields(valid: set[str]) -> list[tuple[str, str, str]]:
    out = []
    for key, name, kind in SAMPLE_FIELDS:
        old = name.replace("clocks_event_reasons", OLD_NAMES["clocks_event_reasons"])
        if name in valid:
            out.append((key, name, kind))
        elif old in valid:
            out.append((key, old, kind))
    return out


def sample(runner, fields, gpu: int) -> dict:
    query = ",".join(n for _, n, _ in fields)
    r = runner.run(["nvidia-smi", f"--id={gpu}", f"--query-gpu={query}", "--format=csv,noheader,nounits"])
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout).strip()[:200]}
    cells = [c.strip() for c in r.stdout.strip().split(",")]
    if len(cells) != len(fields):
        return {"error": f"expected {len(fields)} values, got {len(cells)}"}
    out = {}
    for (key, _, kind), raw in zip(fields, cells):
        status, value = parse_cell(raw, kind)
        out[key] = value if status == "value" else None
    return out


def wait_until_idle(read_util, limit: int = 10, attempts: int = 12, interval: float = 5.0, sleep=time.sleep) -> dict:
    """Takes repeated readings, because a stale first reading can show old load (seen on real runs)."""
    seen = []
    for i in range(attempts):
        util = read_util()
        seen.append(util)
        if util is not None and util <= limit:
            return {"idle": True, "readings": seen}
        if i < attempts - 1:
            sleep(interval)
    return {"idle": False, "readings": seen}


def energy_wh(samples: list[dict]) -> float | None:
    """GPU-only energy from power readings over time. It excludes the rest of the machine."""
    pts = [(s["elapsed"], s["power_draw"]) for s in samples if s.get("elapsed") is not None and s.get("power_draw") is not None]
    if len(pts) < 2:
        return None
    return round(sum((t2 - t1) * (p1 + p2) / 2 for (t1, p1), (t2, p2) in zip(pts, pts[1:])) / 3600, 2)


# ---------- rules ----------
@dataclass
class Evidence:
    tool: dict
    samples: list[dict]
    stop: dict
    memory_total: float | None
    driver_before: str | None
    driver_after: str | None
    driver_errors: int | None
    temp_limit: int
    stop_reason: str = "tool_finished"
    extra: list[dict] = field(default_factory=list)


def evaluate(e: Evidence) -> dict:
    """Applies versioned rules. Returns overall state, findings, and summary numbers."""
    f: list[dict] = list(e.extra)

    def add(rule, state, text):
        f.append({"rule": rule, "state": state, "text": text})

    good = [s for s in e.samples if "error" not in s]
    temps = [s["temperature_gpu"] for s in good if s.get("temperature_gpu") is not None]
    mem = [s["memory_used"] for s in good if s.get("memory_used") is not None]
    peak_mem = max(mem) if mem else None
    summary = {"samples": len(e.samples), "peak_temp": max(temps) if temps else None, "peak_memory_used": peak_mem,
               "iterations": e.tool.get("iterations"), "stop_reason": e.stop_reason, "gpu_energy_wh": energy_wh(good)}
    tps = e.tool.get("generation_tokens_per_second")
    watts = [s["power_draw"] for s in good if s.get("power_draw") is not None and (s.get("gpu_util") or 0) > 50]
    if tps is not None:
        summary["generation_tokens_per_second"] = tps
        summary["prompt_tokens_per_second"] = e.tool.get("prompt_tokens_per_second")
        if watts:
            summary["tokens_per_gpu_watt_hour"] = round(tps * 3600 / (sum(watts) / len(watts)))

    if e.tool.get("failure_lines"):
        add("MEM-001", "FAIL", "The tool's output contains failure text: " + e.tool["failure_lines"][0])
    if e.driver_errors:
        add("DRV-001", "ATTENTION", f"{e.driver_errors} Nvidia driver errors were logged during the run.")
    if e.driver_errors is None:
        add("DRV-002", "NOTE", "Driver error logs weren't collected for this run.")
    if e.driver_before and e.driver_after and e.driver_before != e.driver_after:
        add("DRV-003", "INCONCLUSIVE", f"The driver changed during the run, from {e.driver_before} to {e.driver_after}.")
    if not e.stop.get("stopped"):
        add("RUN-001", "INCONCLUSIVE", "The test tool could not be confirmed stopped.")
    if not e.tool.get("completed"):
        add("RUN-002", "INCONCLUSIVE", f"The tool didn't report completion. Stop reason: {e.stop_reason}.")
    if any("error" in s for s in e.samples):
        add("RUN-003", "INCONCLUSIVE", "One or more telemetry readings failed.")
    if not good:
        add("RUN-004", "INCONCLUSIVE", "No usable telemetry was recorded.")
    if e.stop_reason == "temperature_limit":
        add("THM-001", "INCONCLUSIVE", f"Stopped at the {e.temp_limit} C safety limit, so the test didn't finish.")
    n = sum(1 for s in good if s.get("sw_thermal") == "Active" or s.get("hw_thermal") == "Active")
    if n:
        add("THM-002", "ATTENTION", f"Thermal slowdown appeared in {n} of {len(good)} samples. Check cooling first.")
    if peak_mem and e.memory_total:
        pct = 100 * peak_mem / e.memory_total
        summary["memory_coverage_percent"] = round(pct, 1)
        add("MEM-002", "NOTE", f"Up to {peak_mem:.0f} of {e.memory_total:.0f} MiB ({pct:.0f}%) was in use, so this doesn't prove the whole memory was tested.")
    add("LIM-001", "NOTE", "A pass only covers this tool, date, and setup. It doesn't predict lifespan.")

    states = {x["state"] for x in f}
    overall = next((s for s in ("FAIL", "INCONCLUSIVE", "ATTENTION") if s in states), "PASS")
    return {"state": overall, "findings": f, "summary": summary, "rules_version": "draft-1"}


# ---------- orchestration ----------
def driver_error_count(start: dt.datetime, runner) -> int | None:
    """Counts Windows nvlddmkm events since the start. None means not collected."""
    import sys
    if sys.platform != "win32":
        return None
    stamp = start.strftime("%Y-%m-%dT%H:%M:%S")
    ps = ("(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='nvlddmkm';StartTime=[datetime]'" + stamp +
          "'} -ErrorAction SilentlyContinue | Measure-Object).Count")
    r = runner.run(["powershell", "-NoProfile", "-Command", ps])
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else None


def temp_limit_for(details: dict, requested: int | None) -> int:
    limit = requested if requested is not None else DEFAULT_TEMP_LIMIT
    slow = details.get("slowdown_temp")
    return min(limit, int(slow) - SLOWDOWN_MARGIN) if slow else limit


def run_suite(adapters: list, out_dir: Path, max_seconds: int = 420, temp_limit: int | None = None, cooldown: int = 60, runner=None,
              gpu_select: str | None = None) -> dict:
    """Runs tools one at a time, so one tool's leftovers can't silently affect the next."""
    runner = runner or LocalRunner()
    results = []
    for i, adapter in enumerate(adapters):
        if i:
            time.sleep(cooldown)
        r = run_adapter(adapter, out_dir / f"{i + 1}_{adapter.id}", max_seconds=max_seconds, temp_limit=temp_limit, runner=runner,
                        gpu_select=gpu_select)
        results.append(r)
        if r["state"] == "FAIL" or r["summary"].get("stop_reason") in {"temperature_limit", "sensor_failure", "wrong_device"}:
            break
    skipped = [a.id for a in adapters[len(results):]]
    suite = {"state": "INCONCLUSIVE" if skipped and combine(results) != "FAIL" else combine(results), "skipped": skipped, "steps": results}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "suite.json").write_text(json.dumps(suite, indent=2), encoding="utf-8")
    return suite


def run_adapter(adapter, out_dir: Path, gpu_select: str | None = None, max_seconds: int = 420, interval: float = 5.0,
                temp_limit: int | None = None, runner=None) -> dict:
    runner = runner or LocalRunner()
    before, raw = inspect(runner)
    if not before["gpus"]:
        return {"state": "INCONCLUSIVE", "findings": [{"rule": "RUN-005", "state": "INCONCLUSIVE", "text": "No GPU was detected."}], "summary": {}}
    g, why = select_gpu(before, gpu_select)
    if g is None:
        return {"state": "INCONCLUSIVE", "summary": {}, "tool_id": adapter.id, "findings": [{"rule": "RUN-010", "state": "INCONCLUSIVE", "text": why}]}
    count = len(before["gpus"])
    if count > 1 and not getattr(adapter, "reports_device", False):
        # Without the tool naming its device, a result can't be tied to one card.
        return {"state": "INCONCLUSIVE", "summary": {}, "tool_id": adapter.id, "findings": [{"rule": "RUN-006", "state": "INCONCLUSIVE",
                "text": f"More than one GPU is present, and {adapter.id} can't yet be confirmed to use only the selected card, so it didn't run."}]}
    if count > 1:
        adapter.device_label = memtest_label_for(before["gpus"], g)
    # nvidia-smi accepts a PCI bus ID here, which avoids relying on index order (checked on Mint, driver 580.178.04).
    gpu = g["details"].get("pci_bus_id") or g["index"]
    limit = temp_limit_for(g["details"], temp_limit)
    fields = resolve_sample_fields(_valid_fields(raw))
    idle = wait_until_idle(lambda: sample(runner, fields, gpu).get("gpu_util"))
    if not idle["idle"]:
        # Another tool may still be running, which would make this result unreliable.
        return {"state": "INCONCLUSIVE", "summary": {"stop_reason": "gpu_busy"}, "tool_id": adapter.id, "findings": [{"rule": "RUN-007", "state": "INCONCLUSIVE",
                "text": f"The GPU stayed busy across {len(idle['readings'])} readings, so {adapter.id} didn't run."}]}
    out_dir.mkdir(parents=True, exist_ok=False)
    stdout_path, stderr_path, tele_path = out_dir / "tool_stdout.txt", out_dir / "tool_stderr.txt", out_dir / "telemetry.jsonl"
    start = dt.datetime.now()
    samples, reason = [], "time_limit"
    with open(stdout_path, "wb") as so, open(stderr_path, "wb") as se, open(tele_path, "w", encoding="utf-8") as tele:
        proc = subprocess.Popen(adapter.command(), cwd=out_dir, stdout=so, stderr=se, stdin=subprocess.DEVNULL,
                                start_new_session=os.name != "nt")
        t0 = time.monotonic()
        while time.monotonic() - t0 < max_seconds:
            time.sleep(interval)
            s = sample(runner, fields, gpu)
            s["elapsed"] = round(time.monotonic() - t0, 1)
            samples.append(s)
            tele.write(json.dumps(s) + "\n")
            tele.flush()
            if "error" in s:
                reason = "sensor_failure"
                break
            if (s.get("temperature_gpu") or 0) >= limit:
                reason = "temperature_limit"
                break
            if proc.poll() is not None:
                reason = "tool_exited"
                break
            parsed = adapter.parse(stdout_path.read_text(encoding="utf-8", errors="replace"))
            if parsed.get("tested_device") and device_check(parsed["tested_device"], g, count):
                reason = "wrong_device"
                break
            if parsed["completed"]:
                reason = "tool_finished"
                break
            if parsed["failure_lines"]:
                reason = "tool_reported_failure"
                break
        stop = stop_and_confirm(proc)
    leftovers = still_running(Path(adapter.exe).stem, runner)
    if leftovers:
        stop["stopped"] = False
        stop["method"] = "processes_left_running"
    stop["leftovers"] = len(leftovers)
    tool = adapter.parse(stdout_path.read_text(encoding="utf-8", errors="replace"))
    after, _ = inspect(runner)
    g_after, _ = select_gpu(after, g["details"].get("pci_bus_id") or str(g["index"]))
    a = g_after["fields"]["driver_version"]["value"] if g_after else None
    b = g["fields"]["driver_version"]["value"]
    extra = []
    if getattr(adapter, "reports_device", False):
        check = device_check(tool.get("tested_device"), g, count)
        if check:
            extra.append(check)
    if g_after is None:
        extra.append({"rule": "RUN-011", "state": "INCONCLUSIVE", "text": f"The selected card wasn't found after the run: {describe_gpu(g)}."})
    result = evaluate(Evidence(tool=tool, samples=samples, stop=stop, memory_total=g["fields"]["memory_total"]["value"],
                               driver_before=b, driver_after=a, driver_errors=driver_error_count(start, runner),
                               temp_limit=limit, stop_reason=reason, extra=extra))
    result.update(tool_id=adapter.id, tool_version=adapter.version, tool_exit=stop, temp_limit=limit, gpu_name=g["fields"]["name"]["value"],
                  gpu_index=g["index"], gpu_bus_id=g["details"].get("pci_bus_id"), tool_command=adapter.command(),
                  started_at=start.isoformat(timespec="seconds"), before=before, after=after)
    (out_dir / "test.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _valid_fields(raw: dict[str, str]) -> set[str]:
    from .inspect_core import parse_valid_fields
    return parse_valid_fields(raw.get("help_query_gpu.txt", ""))
