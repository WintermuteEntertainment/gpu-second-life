"""Power limit sweep: runs the same workload at several power limits on one card and reports output per watt.

The workload is memtest_vulkan, so "output" is memory traffic (GB/s written plus checked), as the tool reports it.
That's memory-bound work; a compute-heavy workload such as an LLM can have a different best power limit.
This is a benchmark, not a health test: each step is cut off by time on purpose.
"""
from __future__ import annotations

import json
import re
import signal
import sys
import time
from pathlib import Path

from .inspect_core import LocalRunner
from .testing import (Interrupted, MemtestVulkan, _raise_interrupted, _set_handlers, inspect, run_adapter, select_gpu,
                      temp_limit_for)

# Real line: "    642 iteration. Passed 30.0055 seconds  written: 1465.8GB 155.4GB/sec        checked: 2931.5GB 142.5GB/sec"
WINDOW = re.compile(r"(\d+) iteration\. Passed\s+([\d.]+) seconds\s+written:\s+[\d.]+GB\s+([\d.]+)GB/sec\s+checked:\s+[\d.]+GB\s+([\d.]+)GB/sec")
MIN_WINDOW_SECONDS = 10  # memtest_vulkan's first lines cover 0.05, 1 and 5 seconds, while the card is still warming up


def last_full_window(text: str) -> dict | None:
    """The tool's most recent full-length progress report, or None if it hadn't printed one."""
    best = None
    for m in map(WINDOW.search, text.splitlines()):
        if m and float(m.group(2)) >= MIN_WINDOW_SECONDS:
            best = {"window_seconds": float(m.group(2)), "write_gbps": float(m.group(3)), "check_gbps": float(m.group(4))}
    return best


def step_power(samples: list[dict], skip_seconds: float = 10) -> float | None:
    """Average GPU power while loaded, after the warm-up seconds."""
    w = [s["power_draw"] for s in samples if s.get("power_draw") is not None and (s.get("gpu_util") or 0) > 50
         and (s.get("elapsed") or 0) > skip_seconds]
    return round(sum(w) / len(w), 2) if w else None


def summarise_step(limit: float, stdout: str, samples: list[dict]) -> dict:
    window, watts = last_full_window(stdout), step_power(samples)
    temps = [s["temperature_gpu"] for s in samples if s.get("temperature_gpu") is not None]
    out = {"power_limit_w": limit, "avg_power_w": watts, "peak_temp": max(temps) if temps else None,
           "power_cap_samples": sum(1 for s in samples if s.get("sw_power_cap") == "Active"), "samples": len(samples)}
    if window:
        out.update(window)
        out["traffic_gbps"] = round(window["write_gbps"] + window["check_gbps"], 1)
        if watts:
            out["gbps_per_watt"] = round(out["traffic_gbps"] / watts, 3)
    return out


def power_limits(runner, bus_id: str) -> dict | None:
    r = runner.run(["nvidia-smi", f"--id={bus_id}", "--query-gpu=power.limit,power.default_limit,power.min_limit,power.max_limit",
                    "--format=csv,noheader,nounits"])
    try:
        now, default, low, high = (float(x) for x in r.stdout.strip().split(","))
    except ValueError:
        return None
    return {"now": now, "default": default, "min": low, "max": high}


def set_power_limit(runner, bus_id: str, watts: float) -> tuple[bool, str]:
    # Changing the limit needs root on Linux and an administrator shell on Windows. sudo -n never prompts.
    cmd = ["nvidia-smi", "-i", bus_id, "-pl", f"{watts:g}"]
    if sys.platform.startswith("linux"):
        cmd = ["sudo", "-n"] + cmd
    r = runner.run(cmd)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def wait_cool(runner, bus_id: str, target: int = 45, max_wait: int = 180, sleep=time.sleep) -> int | None:
    t = None
    for _ in range(max_wait // 5):
        r = runner.run(["nvidia-smi", f"--id={bus_id}", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"])
        t = int(r.stdout.strip()) if r.stdout.strip().isdigit() else None
        if t is not None and t <= target:
            return t
        sleep(5)
    return t


def run_sweep(tool_path: str, gpu_select: str, limits: list[float], seconds: int, out_dir: Path, runner=None) -> dict:
    runner = runner or LocalRunner()
    report, _ = inspect(runner)
    g, why = select_gpu(report, gpu_select)
    if g is None:
        return {"error": why}
    bus = g["details"].get("pci_bus_id")
    pl = power_limits(runner, bus) if bus else None
    if pl is None:
        return {"error": "The card's power limits couldn't be read."}
    bad = [w for w in limits if not pl["min"] <= w <= pl["max"]]
    if bad:
        return {"error": f"Limits {bad} are outside this card's range of {pl['min']:g} to {pl['max']:g} W."}
    out_dir.mkdir(parents=True, exist_ok=False)
    steps, error = [], None
    old = _set_handlers(_raise_interrupted)
    try:
        for i, watts in enumerate(limits):
            start_temp = wait_cool(runner, bus)
            ok, msg = set_power_limit(runner, bus, watts)
            if not ok:
                error = f"Setting {watts:g} W failed: {msg[:300]}"
                break
            step_dir = out_dir / f"{i + 1}_{watts:g}W"
            r = run_adapter(MemtestVulkan(tool_path), step_dir, gpu_select=bus, max_seconds=seconds, runner=runner)
            stdout = (step_dir / "tool_stdout.txt").read_text(encoding="utf-8", errors="replace") if (step_dir / "tool_stdout.txt").exists() else ""
            tele = step_dir / "telemetry.jsonl"
            samples = [json.loads(x) for x in tele.read_text(encoding="utf-8").splitlines()] if tele.exists() else []
            step = summarise_step(watts, stdout, samples)
            step.update(start_temp=start_temp, stop_reason=r.get("summary", {}).get("stop_reason"),
                        tool_stopped=r.get("tool_exit", {}).get("stopped"), health_state=r.get("state"))
            steps.append(step)
            if step["stop_reason"] not in ("time_limit", "tool_finished"):
                error = f"Step at {watts:g} W ended with {step['stop_reason']}, so the sweep stopped."
                break
    except Interrupted as e:
        error = f"Interrupted ({e})."
    finally:
        _set_handlers(signal.SIG_IGN)
        restored, msg = set_power_limit(runner, bus, pl["default"])
        after = power_limits(runner, bus)
        for sig, h in old.items():
            signal.signal(sig, h)
    best = max((s for s in steps if s.get("gbps_per_watt")), key=lambda s: s["gbps_per_watt"], default=None)
    result = {"gpu": g["fields"]["name"]["value"], "bus_id": bus, "limits_before": pl, "steps": steps, "error": error,
              "restored_to_default": restored and after is not None and after["now"] == pl["default"], "limits_after": after,
              "best_gbps_per_watt": best, "workload": "memtest_vulkan memory traffic, write plus check GB/s",
              "temp_limit": temp_limit_for(g["details"], None)}
    (out_dir / "sweep.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def to_text(result: dict) -> str:
    if result.get("error") and not result.get("steps"):
        return f"Sweep didn't run: {result['error']}"
    lines = [f"Power limit sweep, {result['gpu']} at {result['bus_id']}. Workload: {result['workload']}.", "",
             "| Limit | Avg power | Peak temp | Traffic | GB/s per W | Power-capped samples |", "|---|---|---|---|---|---|"]
    for s in result["steps"]:
        lines.append(f"| {s['power_limit_w']:g} W | {s.get('avg_power_w') or '?'} W | {s.get('peak_temp') or '?'} C | "
                     f"{s.get('traffic_gbps', '?')} GB/s | {s.get('gbps_per_watt', '?')} | {s['power_cap_samples']} of {s['samples']} |")
    b = result.get("best_gbps_per_watt")
    lines += ["", f"Best output per watt: {b['power_limit_w']:g} W ({b['gbps_per_watt']} GB/s per W)." if b else "No step gave a full reading."]
    if result.get("error"):
        lines.append(f"Stopped early: {result['error']}")
    lines.append("Power limit restored to default: " + ("yes" if result["restored_to_default"] else "NO, check it by hand"))
    lines.append("GPU-only power. Memory-bound work; an AI workload may have a different best limit.")
    return "\n".join(lines)
