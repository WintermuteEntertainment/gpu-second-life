"""Tune: raises a card's GPU clock offset in small steps, proves each step with a self-checking stress tool,
backs off at the first problem, confirms the result with a longer run, and always returns the card to stock.

The offset ranges the driver reports are what it accepts, not what is stable. Too high an offset can crash the
driver or hang the machine, so steps are small and the default ceiling is modest.
"""
from __future__ import annotations

import json
import signal
from pathlib import Path

from . import clocks
from .inspect_core import LocalRunner
from .sweep import last_full_window, step_power, wait_cool
from .testing import (GpuBurn, Interrupted, MemtestVulkan, _raise_interrupted, _set_handlers, describe_gpu, inspect, run_adapter,
                      select_gpu, temp_limit_for)

GOOD_STOPS = {"gpu_burn": {"tool_exited", "tool_finished"}, "memtest_vulkan": {"time_limit", "tool_finished"}}
BAD_STATES = {"FAIL", "ATTENTION"}


def plan_offsets(step: int, ceiling: int, driver_max: int) -> list[int]:
    """Offsets to try, in order, never past the ceiling or what the driver accepts."""
    top = min(ceiling, driver_max)
    return list(range(step, top + 1, step)) if step > 0 else []


def step_ok(tool_id: str, result: dict) -> tuple[bool, str]:
    """Whether a step counts as stable, and why not if it doesn't."""
    reason = result.get("summary", {}).get("stop_reason")
    bad = [f for f in result.get("findings", []) if f["state"] in BAD_STATES]
    if bad:
        return False, f"{bad[0]['rule']}: {bad[0]['text']}"
    if reason not in GOOD_STOPS[tool_id]:
        return False, f"The run ended with '{reason}'."
    if tool_id == "gpu_burn" and result.get("state") != "PASS":
        worst = next((f for f in result.get("findings", []) if f["state"] == "INCONCLUSIVE"), None)
        return False, f"{worst['rule']}: {worst['text']}" if worst else f"The run was {result.get('state')}."
    if tool_id == "memtest_vulkan" and any(f["rule"] != "RUN-002" for f in result.get("findings", []) if f["state"] == "INCONCLUSIVE"):
        worst = next(f for f in result["findings"] if f["state"] == "INCONCLUSIVE" and f["rule"] != "RUN-002")
        return False, f"{worst['rule']}: {worst['text']}"
    return True, ""


def summarise(offset: int, tool_id: str, result: dict, step_dir: Path, start_temp) -> dict:
    tele = step_dir / "telemetry.jsonl"
    samples = [json.loads(x) for x in tele.read_text(encoding="utf-8").splitlines()] if tele.exists() else []
    s = result.get("summary", {})
    out = {"gpu_clock_offset_mhz": offset, "start_temp": start_temp, "peak_temp": s.get("peak_temp"), "avg_power_w": step_power(samples),
           "avg_gpu_clock_mhz": s.get("avg_gpu_clock_under_load_mhz"), "power_cap_samples": s.get("power_cap_samples", 0),
           "samples": len(samples), "stop_reason": s.get("stop_reason"), "state": result.get("state")}
    if tool_id == "gpu_burn":
        out["speed"], out["unit"] = s.get("gflops"), "Gflop/s"
    else:
        out_path = step_dir / "tool_stdout.txt"
        window = last_full_window(out_path.read_text(encoding="utf-8", errors="replace")) if out_path.exists() else None
        out["speed"], out["unit"] = (round(window["write_gbps"] + window["check_gbps"], 1) if window else None), "GB/s"
    if out["speed"] and out["avg_power_w"]:
        out["speed_per_watt"] = round(out["speed"] / out["avg_power_w"], 3)
    out["ok"], out["problem"] = step_ok(tool_id, result)
    return out


def reset(gpu_select: str | None, runner=None) -> dict:
    """Returns one card's clock offsets to stock."""
    report, _ = inspect(runner or LocalRunner())
    g, why = select_gpu(report, gpu_select)
    if g is None:
        return {"error": why}
    bus = g["details"].get("pci_bus_id")
    before = clocks.read(bus)
    done = clocks.set_offsets(bus, gpu=0, mem=0)
    return {"gpu": describe_gpu(g), "before": before, "set": done, "after": clocks.read(bus)}


def run_tune(tool_id: str, tool_path: str, gpu_select: str | None, step: int, ceiling: int, seconds: int, confirm_seconds: int,
             out_dir: Path, runner=None) -> dict:
    runner = runner or LocalRunner()
    report, _ = inspect(runner)
    g, why = select_gpu(report, gpu_select)
    if g is None:
        return {"error": why}
    bus = g["details"].get("pci_bus_id")
    if not bus:
        return {"error": "The card's PCI bus ID is unknown, so its clocks can't be set safely."}
    before = clocks.read(bus)
    if "error" in before:
        return {"error": f"The card's clock offsets couldn't be read: {before['error']}"}
    if clocks.non_stock(before):
        return {"error": f"The card already has a clock offset (GPU {before['gpu_offset_mhz']} MHz, memory {before['mem_offset_mhz']} MHz). "
                         "Return it to stock first with: gpudoc tune --reset"}
    offsets = plan_offsets(step, ceiling, before["gpu_offset_max_mhz"])
    if not offsets:
        return {"error": f"No offsets to try with step {step} and ceiling {ceiling} (the driver accepts up to {before['gpu_offset_max_mhz']} MHz)."}
    # A no-change write first, so a permissions problem shows before any stress run.
    probe = clocks.set_offsets(bus, gpu=0)
    if not probe["ok"]:
        return {"error": f"Clock offsets can't be set here: {probe['error']}. This needs root (sudo without a prompt) on Linux or an administrator shell on Windows."}

    def make(n: int):
        return GpuBurn(tool_path, n) if tool_id == "gpu_burn" else MemtestVulkan(tool_path)

    def one(offset: int, n: int, name: str) -> dict:
        start_temp = wait_cool(runner, bus)
        if offset:
            done = clocks.set_offsets(bus, gpu=offset)
            now = clocks.read(bus)
            if not done["ok"] or now.get("gpu_offset_mhz") != offset:
                return {"gpu_clock_offset_mhz": offset, "ok": False, "problem": f"Setting +{offset} MHz failed: {done.get('error') or now}", "not_run": True}
        step_dir = out_dir / name
        limit = n + 60 if tool_id == "gpu_burn" else n
        r = run_adapter(make(n), step_dir, gpu_select=bus, max_seconds=limit, runner=runner)
        return summarise(offset, tool_id, r, step_dir, start_temp)

    out_dir.mkdir(parents=True, exist_ok=False)
    steps, confirms, error, baseline, best = [], [], None, None, None
    old = _set_handlers(_raise_interrupted)
    try:
        baseline = one(0, seconds, "0_stock")
        if not baseline["ok"]:
            error = f"The card didn't pass at stock settings, so nothing was raised. {baseline['problem']}"
        else:
            passed = [0]
            for i, offset in enumerate(offsets):
                s = one(offset, seconds, f"{i + 1}_plus{offset}MHz")
                steps.append(s)
                if not s["ok"]:
                    break
                passed.append(offset)
            # Confirm the highest passing offset with a longer run; step down while it fails.
            while len(passed) > 1 and best is None:
                c = one(passed[-1], confirm_seconds, f"confirm_plus{passed[-1]}MHz")
                confirms.append(c)
                if c["ok"]:
                    best = c
                else:
                    passed.pop()
    except Interrupted as e:
        error = f"Interrupted ({e})."
    finally:
        _set_handlers(signal.SIG_IGN)
        restore = clocks.set_offsets(bus, gpu=0)
        after = clocks.read(bus)
        for sig, h in old.items():
            signal.signal(sig, h)
    tried = [s for s in [baseline] + steps if s and s.get("ok") and s.get("speed_per_watt")]
    result = {"gpu": g["fields"]["name"]["value"], "bus_id": bus, "workload": tool_id, "clocks_before": before, "step_mhz": step,
              "ceiling_mhz": ceiling, "seconds_per_step": seconds, "confirm_seconds": confirm_seconds, "baseline": baseline, "steps": steps,
              "confirm_runs": confirms, "fastest_stable": best, "most_efficient": max(tried, key=lambda s: s["speed_per_watt"], default=None),
              "first_failure": next((s for s in steps if not s["ok"]), None), "reached_ceiling": bool(steps) and all(s["ok"] for s in steps),
              "error": error, "restored_to_stock": restore["ok"] and after.get("gpu_offset_mhz") == 0 and after.get("mem_offset_mhz") == 0,
              "clocks_after": after, "temp_limit": temp_limit_for(g["details"], None)}
    (out_dir / "tune.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def to_text(result: dict) -> str:
    if result.get("error") and not result.get("baseline"):
        return f"Tune didn't run: {result['error']}"
    b = result["baseline"]
    unit = b.get("unit", "")
    lines = [f"Tune, {result['gpu']} at {result['bus_id']}. Workload: {result['workload']}, {result['seconds_per_step']} s per step.", "",
             "| GPU clock offset | Result | Speed | vs stock | Avg power | Speed per W | Avg clock | Peak temp |", "|---|---|---|---|---|---|---|---|"]

    def row(s, label=None):
        gain = f"{100 * (s['speed'] / b['speed'] - 1):+.1f}%" if s.get("speed") and b.get("speed") and s is not b else ""
        verdict = "stable" if s.get("ok") else "FAILED"
        return (f"| {label or ('+' + str(s['gpu_clock_offset_mhz']) + ' MHz')} | {verdict} | {s.get('speed', '?')} {unit} | {gain} | "
                f"{s.get('avg_power_w') or '?'} W | {s.get('speed_per_watt', '?')} | {s.get('avg_gpu_clock_mhz') or '?'} MHz | {s.get('peak_temp') or '?'} C |")

    lines.append(row(b, "stock"))
    lines += [row(s) for s in result["steps"]]
    lines += [row(c, f"+{c['gpu_clock_offset_mhz']} MHz, {result['confirm_seconds']} s confirm") for c in result["confirm_runs"]]
    lines.append("")
    best, fail = result.get("fastest_stable"), result.get("first_failure")
    if best:
        gain = f", {100 * (best['speed'] / b['speed'] - 1):+.1f}% against stock" if best.get("speed") and b.get("speed") else ""
        lines.append(f"Fastest stable setting found: +{best['gpu_clock_offset_mhz']} MHz{gain}, confirmed over {result['confirm_seconds']} s.")
    else:
        lines.append("No offset above stock was confirmed stable.")
    if fail:
        lines.append(f"First problem at +{fail['gpu_clock_offset_mhz']} MHz: {fail['problem']}")
    elif result.get("reached_ceiling"):
        lines.append(f"Every step up to the +{result['ceiling_mhz']} MHz ceiling passed, so the card's real limit wasn't found.")
    e = result.get("most_efficient")
    if e:
        lines.append(f"Best speed per watt among stable steps: {'stock' if not e['gpu_clock_offset_mhz'] else '+' + str(e['gpu_clock_offset_mhz']) + ' MHz'} "
                     f"({e['speed_per_watt']} {unit} per W).")
    if result.get("error"):
        lines.append(f"Stopped early: {result['error']}")
    lines.append("Card returned to stock clocks: " + ("yes" if result["restored_to_stock"] else "NO, run gpudoc tune --reset"))
    lines.append("Stable here means no errors in this tool for this long. It isn't proof for other workloads, and the setting isn't kept: "
                 "GPUDoc applied it only for these runs.")
    return "\n".join(lines)
