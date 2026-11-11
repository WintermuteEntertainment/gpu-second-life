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
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import clocks
from .inspect_core import LocalRunner, inspect, parse_cell

SAMPLE_FIELDS = [
    ("temperature_gpu", "temperature.gpu", "int"), ("fan_speed", "fan.speed", "int"), ("power_draw", "power.draw", "float"),
    ("gpu_util", "utilization.gpu", "int"), ("memory_used", "memory.used", "int"), ("pstate", "pstate", "str"),
    ("hw_thermal", "clocks_event_reasons.hw_thermal_slowdown", "str"), ("sw_thermal", "clocks_event_reasons.sw_thermal_slowdown", "str"),
    ("sw_power_cap", "clocks_event_reasons.sw_power_cap", "str"), ("driver_version", "driver_version", "str"),
    # Clock speeds and the full reasons value show a card running slow even when no single slowdown flag is set.
    ("clock_gpu", "clocks.current.graphics", "int"), ("clock_mem", "clocks.current.memory", "int"),
    ("slowdown_reasons", "clocks_event_reasons.active", "str"),
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

    def prepare(self, gpus: list[dict], target: dict, runner) -> str | None:
        if len(gpus) > 1:
            self.device_label = memtest_label_for(gpus, target)
        return None

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
    """Adapter for llama-bench JSONL output, read from real b12177 Vulkan runs on Windows and Linux."""

    id = "llama_bench"
    version = "llama.cpp build reported in results"
    stdout_only = True
    memory_test = False
    # Real line from --list-devices: "  Vulkan0: NVIDIA GeForce GTX 1660 Ti (6390 MiB, 5411 MiB free)"
    DEVICE = re.compile(r"^\s+([A-Za-z]+\d+): (.+) \(\d+ MiB, \d+ MiB free\)\s*$")

    def __init__(self, exe: str, model: str, repetitions: int = 3, device: str | None = None):
        self.exe, self.model, self.repetitions, self.device = exe, model, repetitions, device

    @classmethod
    def parse_devices(cls, text: str) -> list[tuple[str, str]]:
        """(device, card name) pairs from llama-bench --list-devices."""
        return [(m.group(1), m.group(2).strip()) for m in map(cls.DEVICE.match, text.splitlines()) if m]

    def prepare(self, gpus: list[dict], target: dict, runner) -> str | None:
        """With several cards, picks the tool's device for the selected card by name. The list has no bus IDs,
        so two cards with the same name can't be told apart here; the run also watches every card's memory."""
        if len(gpus) == 1:
            return None
        r = runner.run([self.exe, "--list-devices"])
        name = target["fields"]["name"]["value"]
        match = [d for d, n in self.parse_devices(r.stdout + "\n" + r.stderr) if n == name]
        if len(match) != 1:
            return (f"llama-bench lists {len(match)} devices named '{name}', so the selected card can't be picked for certain, "
                    "and it didn't run.")
        self.device = match[0]
        return None

    def verify(self, tool: dict) -> dict | None:
        if self.device and tool.get("devices") != self.device:
            return {"rule": "RUN-008", "state": "INCONCLUSIVE", "text": (
                f"llama-bench reported device '{tool.get('devices')}', not the requested '{self.device}'. "
                "The result doesn't apply to the selected card.")}
        return None

    def command(self) -> list[str]:
        return ([self.exe, "-m", self.model] + (["-dev", self.device] if self.device else []) +
                ["-ngl", "99", "-p", "512", "-n", "256", "-r", str(self.repetitions), "-o", "jsonl"])

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
            "devices": rows[-1].get("devices") if rows else None, "memory_test": False,
        }


class GpuBurn:
    """Adapter for gpu-burn (github.com/wilicc/gpu-burn, commit 0d19c94), a CUDA compute stress test that checks
    its own results. Linux only. The output format was read from real runs on Noodlecart."""

    id = "gpu_burn"
    version = "commit 0d19c94"
    memory_test = False
    # CUDA numbers cards fastest first unless told otherwise. This makes it follow PCI bus order, as nvidia-smi does.
    env = {"CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
    LISTED = re.compile(r"^ID (\d+): (.+), \d+MB\s*$")
    PROGRESS = re.compile(r"([\d.]+)%\s+proc'd: (-?\d+) \((\d+) Gflop/s\)\s+errors: (-?\d+)")
    RESULT = re.compile(r"^\s*GPU (\d+): (\w+)\s*$")

    def __init__(self, exe: str, seconds: int = 300, device: int | None = None):
        self.exe, self.seconds, self.device = str(Path(exe).resolve()), seconds, device
        # gpu-burn loads compare.fatbin from the current folder, so it runs from its own.
        self.cwd = Path(self.exe).parent

    @classmethod
    def parse_list(cls, text: str) -> dict[int, str]:
        """Device number to card name, from gpu_burn -l."""
        return {int(m.group(1)): m.group(2).strip() for m in map(cls.LISTED.match, text.splitlines()) if m}

    def list_devices(self) -> str:
        p = subprocess.run([self.exe, "-l"], cwd=self.cwd, env={**os.environ, **self.env}, capture_output=True, text=True, timeout=60)
        return p.stdout

    def prepare(self, gpus: list[dict], target: dict, runner) -> str | None:
        if not sys.platform.startswith("linux"):
            return "gpu-burn only runs on Linux, so it didn't run."
        if len(gpus) == 1:
            return None
        keyed = [(parse_bus_id(g["details"].get("pci_bus_id")), g) for g in gpus]
        if any(k is None for k, _ in keyed):
            return "A card's PCI bus ID is unknown, so gpu-burn's device number can't be worked out, and it didn't run."
        number = next(i for i, (_, g) in enumerate(sorted(keyed, key=lambda kg: kg[0])) if g is target)
        name = target["fields"]["name"]["value"]
        listed = self.parse_list(self.list_devices())
        if listed.get(number) != name:
            return (f"gpu-burn lists device {number} as '{listed.get(number)}', not '{name}', so the selected card can't be "
                    "picked for certain, and it didn't run.")
        self.device = number
        return None

    def command(self) -> list[str]:
        return [self.exe] + (["-i", str(self.device)] if self.device is not None else []) + [str(self.seconds)]

    def parse(self, text: str) -> dict:
        # Progress lines overwrite each other with carriage returns.
        lines = text.replace("\r", "\n").splitlines()
        progress = [m for m in map(self.PROGRESS.search, lines) if m]
        results = [m.group(2) for m in map(self.RESULT.match, lines) if m]
        # No real failing gpu-burn log exists yet, so these two matches are unverified. A match can only make a run fail.
        bad = [m.group(0) for m in progress if int(m.group(4)) != 0 or int(m.group(2)) < 0]
        bad += [line.strip() for line in lines if self.RESULT.match(line) and not line.strip().endswith(": OK")]
        return {
            "completed": any(line.startswith("Tested ") for line in lines) and bool(results) and all(r == "OK" for r in results),
            "failure_lines": list(dict.fromkeys(bad))[:20],
            "iterations": int(progress[-1].group(2)) if progress else 0,
            "started": any(line.startswith("Burning for") for line in lines),
            "gflops": int(progress[-1].group(3)) if progress else None,
            "memory_test": False,
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


LOAD_MIB = 512


def memory_by_bus(runner) -> dict | None:
    """Memory in use on every card, keyed by PCI bus. None if it couldn't be read."""
    r = runner.run(["nvidia-smi", "--query-gpu=pci.bus_id,memory.used", "--format=csv,noheader,nounits"])
    if r.returncode != 0:
        return None
    out = {}
    for line in r.stdout.strip().splitlines():
        bus, _, used = line.rpartition(",")
        key = parse_bus_id(bus)
        try:
            out[key] = float(used)
        except ValueError:
            return None
        if key is None:
            return None
    return out or None


def track_load(usage: dict, reading: dict | None) -> None:
    """Keeps each card's highest memory use seen during the run."""
    if reading is None:
        usage["failed"] = True
        return
    for bus, used in reading.items():
        usage["peak"][bus] = max(used, usage["peak"].get(bus, used))


def load_rise(usage: dict) -> dict:
    """How far each card's memory use rose above its level before the tool started, in MiB."""
    base = usage.get("baseline") or {}
    return {bus: peak - base[bus] for bus, peak in usage["peak"].items() if bus in base}


def strayed(usage: dict, bus: tuple | None) -> list[tuple]:
    """Other cards whose memory use rose enough to show they took load."""
    return [b for b, rise in load_rise(usage).items() if b != bus and rise >= LOAD_MIB]


def load_findings(usage: dict, bus: tuple | None) -> list[dict]:
    """For tools that don't name their card by bus: confirms from memory use that the selected card,
    and only that card, carried the load."""
    rise = load_rise(usage)
    if usage.get("failed") or not usage.get("baseline") or bus not in rise:
        return [{"rule": "RUN-009", "state": "INCONCLUSIVE", "text": "Memory use on every card couldn't be read throughout the run, "
                 "so the card that carried the load can't be confirmed."}]
    out = []
    for b in strayed(usage, bus):
        out.append({"rule": "RUN-014", "state": "INCONCLUSIVE", "text": f"Memory use on another card (bus {b[1]:02x}:{b[2]:02x}) rose by "
                    f"{rise[b]:.0f} MiB during the run, so the load didn't stay on the selected card."})
    if rise[bus] < LOAD_MIB:
        out.append({"rule": "RUN-015", "state": "INCONCLUSIVE", "text": f"Memory use on the selected card rose by only {rise[bus]:.0f} MiB, "
                    "so there's no sign it carried the load."})
    return out


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
    target_temp: float | None = None
    xid_codes: list[int] = field(default_factory=list)
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
    clocks = [s["clock_gpu"] for s in good if s.get("clock_gpu") is not None and (s.get("gpu_util") or 0) > 50]
    if watts:
        summary["avg_power_under_load_w"] = round(sum(watts) / len(watts), 1)
    if clocks:
        summary["avg_gpu_clock_under_load_mhz"] = round(sum(clocks) / len(clocks))
    if e.tool.get("gflops") is not None:
        summary["gflops"] = e.tool["gflops"]
        if watts:
            summary["gflops_per_gpu_watt"] = round(e.tool["gflops"] / (sum(watts) / len(watts)), 1)
    if tps is not None:
        summary["generation_tokens_per_second"] = tps
        summary["prompt_tokens_per_second"] = e.tool.get("prompt_tokens_per_second")
        if watts:
            summary["tokens_per_gpu_watt_hour"] = round(tps * 3600 / (sum(watts) / len(watts)))

    if e.tool.get("failure_lines"):
        rule = "MEM-001" if e.tool.get("memory_test", True) else "CMP-001"
        add(rule, "FAIL", "The tool's output contains failure text: " + e.tool["failure_lines"][0])
    if 48 in e.xid_codes:
        add("DRV-004", "FAIL", "Xid 48, an uncorrectable (double-bit) ECC memory error, was logged for this card during the run.")
    if e.driver_errors:
        codes = f" (Xid {', '.join(map(str, sorted(set(e.xid_codes))))})" if e.xid_codes else ""
        add("DRV-001", "ATTENTION", f"{e.driver_errors} Nvidia driver errors{codes} were logged for this card during the run.")
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
    hw = sum(1 for s in good if s.get("hw_thermal") == "Active")
    sw = sum(1 for s in good if s.get("sw_thermal") == "Active")
    if hw:
        add("THM-002", "ATTENTION", f"Hardware thermal slowdown appeared in {hw} of {len(good)} samples. Check cooling first.")
    cap = sum(1 for s in good if s.get("sw_power_cap") == "Active")
    if cap:
        summary["power_cap_samples"] = cap
        add("PWR-001", "NOTE", f"The card's power limit held clocks back in {cap} of {len(good)} samples. "
            "Speed and energy figures from this run reflect that limit.")
    # Seen on Noodlecart: with the desktop locked, the card driving the monitor ran at exactly 1200 MHz under load,
    # about 27% slower, while the driver reported no reason. A card can also sit at one clock when nothing limits it.
    loaded = [s for s in good if s.get("clock_gpu") is not None and (s.get("gpu_util") or 0) > 50]
    limited = any(s.get(k) == "Active" for s in loaded for k in ("hw_thermal", "sw_thermal", "sw_power_cap"))
    if len(loaded) >= 3 and len({s["clock_gpu"] for s in loaded}) == 1 and not limited:
        summary["pinned_gpu_clock_mhz"] = loaded[0]["clock_gpu"]
        add("CLK-001", "NOTE", f"The GPU clock stayed at exactly {loaded[0]['clock_gpu']} MHz in all {len(loaded)} samples under load, "
            "and the driver gave no reason. This can be the card's normal top speed, or a cap from outside the test, such as a "
            "locked or sleeping desktop or a power-saving setting. Compare speed figures only with runs at the same clock.")
    if sw:
        target = f" The card's target temperature is {e.target_temp:.0f} C." if e.target_temp else ""
        add("THM-003", "NOTE", f"The driver lowered clocks to control temperature in {sw} of {len(good)} samples, peaking at "
            f"{summary['peak_temp']} C.{target} This is the driver's normal temperature control, not a fault by itself.")
    if peak_mem and e.memory_total and e.tool.get("memory_test", True):
        pct = 100 * peak_mem / e.memory_total
        summary["memory_coverage_percent"] = round(pct, 1)
        add("MEM-002", "NOTE", f"Up to {peak_mem:.0f} of {e.memory_total:.0f} MiB ({pct:.0f}%) was in use, so this doesn't prove the whole memory was tested.")
    add("LIM-001", "NOTE", "A pass only covers this tool, date, and setup. It doesn't predict lifespan.")

    states = {x["state"] for x in f}
    overall = next((s for s in ("FAIL", "INCONCLUSIVE", "ATTENTION") if s in states), "PASS")
    return {"state": overall, "findings": f, "summary": summary, "rules_version": "draft-6"}


# ---------- orchestration ----------
# Nvidia's documented kernel log form, e.g. "NVRM: Xid (PCI:0000:01:00): 79, pid=...". No real Xid line has been
# captured on Noodlecart yet, so this match is unverified. It can only add findings, never remove them.
XID = re.compile(r"NVRM: Xid \(PCI:([0-9A-Fa-f]{4}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2})\): (\d+)")


def parse_xid(text: str, bus: tuple | None) -> dict:
    """Xid events for the selected card (all cards if its bus is unknown), plus a count for other cards."""
    mine, other = [], 0
    for line in text.splitlines():
        m = XID.search(line)
        if not m:
            continue
        where = (int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16))
        if bus is None or where == bus[:3]:
            mine.append((int(m.group(4)), line.strip()))
        else:
            other += 1
    return {"count": len(mine), "codes": [c for c, _ in mine], "lines": [ln for _, ln in mine][:10], "other_cards": other}


def driver_errors(start: dt.datetime, runner, bus_id: str | None) -> dict | None:
    """Reads the driver's error log once, after the run. None means it couldn't be read."""
    if sys.platform == "win32":
        stamp = start.strftime("%Y-%m-%dT%H:%M:%S")
        ps = ("(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='nvlddmkm';StartTime=[datetime]'" + stamp +
              "'} -ErrorAction SilentlyContinue | Measure-Object).Count")
        r = runner.run(["powershell", "-NoProfile", "-Command", ps])
        if r.returncode == 0 and r.stdout.strip().isdigit():
            return {"count": int(r.stdout.strip()), "codes": [], "source": "Windows System log, nvlddmkm"}
        return None
    if sys.platform.startswith("linux"):
        # One read of the kernel log since the start. Works without root for members of the adm group.
        r = runner.run(["journalctl", "-k", "--since", f"@{int(start.timestamp())}", "-o", "short-iso", "--no-pager", "-q"])
        if r.returncode != 0:
            return None
        return dict(parse_xid(r.stdout, parse_bus_id(bus_id)), source="kernel log, journalctl -k")
    return None


class Interrupted(Exception):
    pass


# SIGBREAK is Windows' Ctrl+Break. SIGHUP is Linux's "terminal closed".
INTERRUPT_SIGNALS = [s for s in ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK") if hasattr(signal, s)]


def _raise_interrupted(signum, _frame):
    raise Interrupted(signal.Signals(signum).name)


def _set_handlers(handler) -> dict:
    old = {}
    for name in INTERRUPT_SIGNALS:
        sig = getattr(signal, name)
        old[sig] = signal.signal(sig, handler)
    return old


def _die_with_parent():
    """Linux only: the kernel kills the tool if GPUDoc itself is killed, so a stress test can't run on unwatched."""
    import ctypes
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)  # 1 = PR_SET_PDEATHSIG


def kill_with_parent_windows(proc) -> bool:
    """Windows: puts the tool in a job object set to kill everything in it when the job's last handle closes.
    GPUDoc holds that handle, so Windows ends the tool and any child it starts later if GPUDoc exits for any reason."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_ulonglong * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # 9 = JobObjectExtendedLimitInformation
    # The handle is deliberately never closed: it closes when GPUDoc's process ends, which ends the tool.
    return bool(ok and k32.AssignProcessToJobObject(job, int(proc._handle)))


def start_tool(cmd: list[str], cwd: Path, stdout, stderr, env: dict | None = None) -> tuple[subprocess.Popen, str]:
    """Starts a stress tool so it can't outlive GPUDoc. Returns the process and how that's guaranteed."""
    linux = sys.platform.startswith("linux")
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, start_new_session=os.name != "nt",
                            env={**os.environ, **env} if env else None, preexec_fn=_die_with_parent if linux else None)
    if linux:
        return proc, "linux_pdeathsig"
    if os.name == "nt":
        # A child the tool starts in the first instant, before this call, would escape the job; taskkill /T still stops it normally.
        return proc, "windows_job_object" if kill_with_parent_windows(proc) else "none"
    return proc, "none"


def temp_limit_for(details: dict, requested: int | None) -> int:
    """Stop limit from the card's own reported limits: 5 C below the lower of its slowdown temperature and
    its maximum operating temperature. A requested limit can only lower it. With no card limits, 85 C."""
    card = [int(v) - SLOWDOWN_MARGIN for v in (details.get("slowdown_temp"), details.get("max_operating_temp")) if v]
    limit = min(card) if card else DEFAULT_TEMP_LIMIT
    return min(limit, requested) if requested is not None else limit


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
        if r["state"] == "FAIL" or r["summary"].get("stop_reason") in {"temperature_limit", "sensor_failure", "wrong_device", "interrupted"}:
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
    # Each tool works out its own device number for the selected card, or says why it can't.
    if hasattr(adapter, "prepare"):
        why = adapter.prepare(before["gpus"], g, runner)
    else:
        why = f"More than one GPU is present, and {adapter.id} can't be pointed at the selected card, so it didn't run." if count > 1 else None
    if why:
        return {"state": "INCONCLUSIVE", "summary": {}, "tool_id": adapter.id, "findings": [{"rule": "RUN-006", "state": "INCONCLUSIVE", "text": why}]}
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
    samples, interrupted_by = [], None
    bus_now = g["details"].get("pci_bus_id")
    offsets = clocks.read(bus_now) if bus_now and runner.mode == "local" else {"error": "not read"}
    # A tool that doesn't name its card by bus is checked by watching memory use on every card.
    usage = None
    if count > 1 and not getattr(adapter, "reports_device", False):
        base = memory_by_bus(runner)
        usage = {"baseline": base, "peak": dict(base or {}), "failed": base is None}
    # Ctrl+C, a terminal closing, or a kill request stops the tool and still writes an INCONCLUSIVE result.
    old_handlers = _set_handlers(_raise_interrupted)
    try:
        with open(stdout_path, "wb") as so, open(stderr_path, "wb") as se, open(tele_path, "w", encoding="utf-8") as tele:
            proc, guard = start_tool(adapter.command(), getattr(adapter, "cwd", None) or out_dir, so, se, getattr(adapter, "env", None))
            try:
                reason = _watch(proc, adapter, runner, fields, gpu, g, count, limit, max_seconds, interval, stdout_path, samples, tele, usage)
            except Interrupted as e:
                reason, interrupted_by = "interrupted", str(e)
            _set_handlers(signal.SIG_IGN)  # further signals wait until the tool is stopped and the result is written
            stop = stop_and_confirm(proc)
        leftovers = still_running(Path(adapter.exe).stem, runner)
        if leftovers:
            stop["stopped"] = False
            stop["method"] = "processes_left_running"
        stop["leftovers"] = len(leftovers)
        tool = adapter.parse(stdout_path.read_text(encoding="utf-8", errors="replace"))
        after, _ = inspect(runner)
        bus_id = g["details"].get("pci_bus_id")
        g_after, _ = select_gpu(after, bus_id or str(g["index"]))
        a = g_after["fields"]["driver_version"]["value"] if g_after else None
        b = g["fields"]["driver_version"]["value"]
        extra = []
        stop["guard"] = guard
        if offsets.get("error"):
            extra.append({"rule": "SET-002", "state": "NOTE", "text": "The card's clock offsets couldn't be read, so it isn't known whether it ran at stock settings."})
        elif clocks.non_stock(offsets):
            extra.append({"rule": "SET-001", "state": "NOTE", "text": (
                f"This run was taken at non-stock clocks: GPU {offsets['gpu_offset_mhz']:+d} MHz, memory {offsets['mem_offset_mhz']:+d} MHz. "
                "Don't compare its figures with stock runs, and don't read it as the card's condition at stock.")})
        if guard == "none":
            extra.append({"rule": "RUN-013", "state": "NOTE", "text": "The tool wasn't tied to GPUDoc's lifetime on this system, so a crash of GPUDoc itself could leave it running."})
        if interrupted_by:
            extra.append({"rule": "RUN-012", "state": "INCONCLUSIVE", "text": f"The run was interrupted ({interrupted_by}) before the tool finished."})
        if getattr(adapter, "reports_device", False):
            check = device_check(tool.get("tested_device"), g, count)
            if check:
                extra.append(check)
        if hasattr(adapter, "verify"):
            check = adapter.verify(tool)
            if check:
                extra.append(check)
        if usage is not None:
            extra.extend(load_findings(usage, parse_bus_id(bus_id)))
        if g_after is None:
            extra.append({"rule": "RUN-011", "state": "INCONCLUSIVE", "text": f"The selected card wasn't found after the run: {describe_gpu(g)}."})
        log = driver_errors(start, runner, bus_id)
        result = evaluate(Evidence(tool=tool, samples=samples, stop=stop, memory_total=g["fields"]["memory_total"]["value"],
                                   driver_before=b, driver_after=a, driver_errors=log["count"] if log else None,
                                   temp_limit=limit, stop_reason=reason, extra=extra, target_temp=g["details"].get("target_temp"),
                                   xid_codes=log.get("codes", []) if log else []))
        result.update(tool_id=adapter.id, tool_version=adapter.version, tool_exit=stop, temp_limit=limit, gpu_name=g["fields"]["name"]["value"],
                      gpu_index=g["index"], gpu_bus_id=bus_id, tool_command=adapter.command(), driver_log=log,
                      clock_offsets=offsets, stock_settings=None if offsets.get("error") else not clocks.non_stock(offsets),
                      memory_rise_mib={f"{b[1]:02x}:{b[2]:02x}.{b[3]}": r for b, r in load_rise(usage).items()} if usage else None,
                      started_at=start.isoformat(timespec="seconds"), before=before, after=after)
        (out_dir / "test.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def _watch(proc, adapter, runner, fields, gpu, g, count, limit, max_seconds, interval, stdout_path, samples, tele, usage=None) -> str:
    """Samples the card until something ends the run, and returns why it ended."""
    bus = parse_bus_id(g["details"].get("pci_bus_id"))
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_seconds:
        time.sleep(interval)
        s = sample(runner, fields, gpu)
        s["elapsed"] = round(time.monotonic() - t0, 1)
        samples.append(s)
        tele.write(json.dumps(s) + "\n")
        tele.flush()
        if "error" in s:
            return "sensor_failure"
        if (s.get("temperature_gpu") or 0) >= limit:
            return "temperature_limit"
        if usage is not None:
            track_load(usage, memory_by_bus(runner))
            if strayed(usage, bus):
                return "wrong_device"
        if proc.poll() is not None:
            return "tool_exited"
        parsed = adapter.parse(stdout_path.read_text(encoding="utf-8", errors="replace"))
        if parsed.get("tested_device") and device_check(parsed["tested_device"], g, count):
            return "wrong_device"
        if parsed["completed"]:
            return "tool_finished"
        if parsed["failure_lines"]:
            return "tool_reported_failure"
    return "time_limit"


def _valid_fields(raw: dict[str, str]) -> set[str]:
    from .inspect_core import parse_valid_fields
    return parse_valid_fields(raw.get("help_query_gpu.txt", ""))
