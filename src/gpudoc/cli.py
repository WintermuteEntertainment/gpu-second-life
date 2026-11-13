"""Command line entry point."""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import platform
import sys
from pathlib import Path

from . import __version__
from .inspect_core import CaptureRunner, LocalRunner, SshRunner, inspect, redact, to_markdown
from .report_html import to_html


def new_run_dir(base: Path) -> Path:
    stem = "inspect-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for n in range(100):
        d = base / (stem if n == 0 else f"{stem}-{n}")
        try:
            d.mkdir(parents=True)
            return d
        except FileExistsError:
            continue
    raise RuntimeError("could not create a new run folder")


def cmd_inspect(a) -> int:
    runner = CaptureRunner(a.from_capture) if a.from_capture else SshRunner(a.ssh) if a.ssh else LocalRunner()
    report, raw = inspect(runner)
    report["tool_version"] = __version__
    report["collected_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    if runner.mode == "local":
        report["host"] = {"hostname": platform.node(), "user": getpass.getuser(), "os": platform.platform()}
        report["environment"] = "wsl" if "microsoft" in platform.release().lower() else sys.platform
    elif runner.mode == "ssh":
        report["host"] = {"target": a.ssh}
    d = new_run_dir(Path(a.out))
    (d / "raw").mkdir()
    for name, text in raw.items():
        (d / "raw" / name).write_text(text, encoding="utf-8")
    (d / "inspect.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (d / "inspect.md").write_text(to_markdown(report), encoding="utf-8")
    safe = redact(report)
    (d / "inspect.redacted.json").write_text(json.dumps(safe, indent=2), encoding="utf-8")
    (d / "inspect.redacted.md").write_text(to_markdown(safe), encoding="utf-8")
    (d / "inspect.html").write_text(to_html(report), encoding="utf-8")
    (d / "inspect.redacted.html").write_text(to_html(safe), encoding="utf-8")
    print(to_markdown(safe if a.redact else report))
    print(f"Saved to {d}. Share only the inspect.redacted files; raw and inspect.* contain identifiers.")
    return 0 if report["complete"] else 2


def cmd_test(a) -> int:
    from .testing import DcgmDiag, GpuBurn, GpuFryer, LlamaBench, LocalScore, MemtestVulkan, Wattever, describe_gpu, run_suite, select_gpu, temp_limit_for
    adapters = [MemtestVulkan(a.tool_path)] if a.tool_path else []
    if a.gpu_burn:
        if not (sys.platform.startswith("linux") or os.name == "nt"):
            print("Nothing was run. gpu-burn runs on Linux and Windows only.")
            return 3
        if a.burn_seconds + 60 > a.max_seconds:
            print(f"Nothing was run. --burn-seconds {a.burn_seconds} needs --max-seconds of at least {a.burn_seconds + 60}.")
            return 3
        adapters.append(GpuBurn(a.gpu_burn, a.burn_seconds))
    if a.dcgm:
        adapters.insert(0, DcgmDiag(a.dcgm, a.dcgm_level))
    if a.gpu_fryer:
        if not sys.platform.startswith("linux"):
            print("Nothing was run. gpu-fryer only runs on Linux.")
            return 3
        if a.fryer_seconds + 60 > a.max_seconds:
            print(f"Nothing was run. --fryer-seconds {a.fryer_seconds} needs --max-seconds of at least {a.fryer_seconds + 60}.")
            return 3
        adapters.append(GpuFryer(a.gpu_fryer, a.fryer_seconds))
    if a.llama_bench or (a.model and not a.wattever):
        if not (a.llama_bench and a.model):
            print("--llama-bench and --model must be used together.")
            return 3
        # The tool is started from the run folder, so both paths must not depend on the current folder.
        adapters.append(LlamaBench(str(Path(a.llama_bench).resolve()), str(Path(a.model).resolve())))
    if a.localscore or a.localscore_model:
        if not (a.localscore and a.localscore_model):
            print("--localscore and --localscore-model must be used together.")
            return 3
        adapters.append(LocalScore(a.localscore, a.localscore_model))
    if a.wattever:
        if not (a.llama_server and a.model):
            print("--wattever needs --llama-server and --model.")
            return 3
        adapters.append(Wattever(a.wattever, a.llama_server, a.model))
    if not adapters:
        print("Nothing was run. Choose at least one tool: --tool-path (memtest_vulkan), --gpu-burn, --gpu-fryer, --dcgm, or --llama-bench with --model.")
        return 3
    report, _ = inspect(LocalRunner())
    if a.gpu == "all":
        cards = report["gpus"]
        if not cards:
            print("Nothing was run. No GPU was detected.")
            return 3
    else:
        g, why = select_gpu(report, a.gpu)
        if g is None:
            print(f"Nothing was run. {why}")
            return 3
        cards = [g]
    print("These tests stress the GPU and raise its temperature, and they could expose or worsen an existing fault.")
    if len(cards) > 1:
        print(f"Each card is tested on its own, one after another: {len(cards)} cards.")
    for g in cards:
        d_ = g["details"]
        reported = ", ".join(f"{label} {d_[k]:.0f} C" for k, label in (("slowdown_temp", "slowdown"), ("max_operating_temp", "max operating"),
                                                                       ("target_temp", "target")) if d_.get(k))
        print(f"Card: {describe_gpu(g)}. Stop limit: {temp_limit_for(d_, a.temp_limit)} C (card reports {reported or 'no limits'}).")
    print(f"Tools: {', '.join(x.id for x in adapters)}. Time limit per tool: {a.max_seconds} s.")
    if not a.yes and input("Type YES to continue: ").strip() != "YES":
        print("Cancelled. Nothing was run.")
        return 3
    d = Path(a.out) / ("test-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    states = []
    for g in cards:
        bus = g["details"].get("pci_bus_id") or str(g["index"])
        card_dir = d if len(cards) == 1 else d / f"gpu{g['index']}_{bus.replace(':', '-')}"
        # The bus ID is passed on, so the card can't change if index order shifts between the check above and the run.
        suite = run_suite(adapters, card_dir, max_seconds=a.max_seconds, temp_limit=a.temp_limit, gpu_select=bus)
        states.append(suite["state"])
        print(f"\n=== {describe_gpu(g)}\nOverall: {suite['state']}")
        for step in suite["steps"]:
            print(f"\n{step.get('tool_id', 'tool')}: {step['state']}")
            for f in step["findings"]:
                print(f"- [{f['state']}] {f['rule']}: {f['text']}")
            print(f"Summary: {step.get('summary')}")
        if suite["skipped"]:
            print(f"\nNot run: {', '.join(suite['skipped'])}")
        if any(st.get("summary", {}).get("stop_reason") == "interrupted" for st in suite["steps"]):
            print("\nInterrupted, so the remaining cards weren't tested.")
            break
    print(f"\nSaved to {d}")
    worst = next((s for s in ("FAIL", "INCONCLUSIVE", "ATTENTION", "PASS") if s in states), "INCONCLUSIVE")
    return {"PASS": 0, "ATTENTION": 0, "INCONCLUSIVE": 2, "FAIL": 1}[worst]


def cmd_sweep(a) -> int:
    from .sweep import run_sweep, to_text
    from .testing import describe_gpu, select_gpu
    try:
        limits = [float(x) for x in a.limits.split(",") if x.strip()]
    except ValueError:
        print("--limits must be watts separated by commas, such as 70,85,100,120.")
        return 3
    report, _ = inspect(LocalRunner())
    g, why = select_gpu(report, a.gpu)
    if g is None:
        print(f"Nothing was run. {why}")
        return 3
    print("This runs memtest_vulkan at each power limit, which stresses the card. Changing the power limit needs root "
          "(sudo, without a prompt) on Linux or an administrator shell on Windows. The default limit is restored at the end.")
    print(f"Card: {describe_gpu(g)}. Limits: {', '.join(f'{w:g} W' for w in limits)}, {a.seconds} s each.")
    if not a.yes and input("Type YES to continue: ").strip() != "YES":
        print("Cancelled. Nothing was run.")
        return 3
    d = Path(a.out) / ("sweep-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    result = run_sweep(a.tool_path, g["details"].get("pci_bus_id") or str(g["index"]), limits, a.seconds, d)
    print(to_text(result))
    print(f"Saved to {d}")
    return 0 if result.get("steps") and not result.get("error") else 2


def cmd_tune(a) -> int:
    from .testing import describe_gpu, select_gpu
    from .tune import reset, run_tune, to_text
    if a.reset:
        r = reset(a.gpu)
        if r.get("error"):
            print(f"Nothing was changed. {r['error']}")
            return 3
        ok = r["set"]["ok"] and not r["after"].get("error") and not r["after"]["gpu_offset_mhz"] and not r["after"]["mem_offset_mhz"]
        print(f"{r['gpu']}: clock offsets " + ("are at stock (0 MHz)." if ok else f"could NOT be reset: {r['set'].get('error') or r['after']}"))
        return 0 if ok else 2
    if bool(a.gpu_burn) == bool(a.tool_path):
        print("Choose one workload: --gpu-burn or --tool-path (memtest_vulkan).")
        return 3
    report, _ = inspect(LocalRunner())
    g, why = select_gpu(report, a.gpu)
    if g is None:
        print(f"Nothing was run. {why}")
        return 3
    tool_id, path = ("gpu_burn", a.gpu_burn) if a.gpu_burn else ("memtest_vulkan", a.tool_path)
    print("This raises the card's GPU clock above stock in steps and stress-tests each one. Too high a setting can crash the "
          "graphics driver or hang the machine. It needs root (sudo without a prompt) on Linux or an administrator shell on Windows. "
          "The card is returned to stock at the end, and nothing is kept.")
    print(f"Card: {describe_gpu(g)}. Workload: {tool_id}. Steps of {a.step} MHz up to +{a.max_offset} MHz, {a.seconds} s each, "
          f"then a {a.confirm_seconds} s confirmation run.")
    if not a.yes and input("Type YES to continue: ").strip() != "YES":
        print("Cancelled. Nothing was run.")
        return 3
    d = Path(a.out) / ("tune-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    result = run_tune(tool_id, path, g["details"].get("pci_bus_id") or str(g["index"]), a.step, a.max_offset, a.seconds, a.confirm_seconds, d)
    print(to_text(result))
    if result.get("baseline"):
        print(f"Saved to {d}")
    return 0 if result.get("baseline") and not result.get("error") and result.get("restored_to_stock") else 2


def cmd_serve(a) -> int:
    from .web import serve
    tools = Path(a.tools) if a.tools else (Path("gpudoc-tools.json") if Path("gpudoc-tools.json").exists() else None)
    if a.tools and not tools.exists():
        print(f"Tools file not found: {tools}")
        return 3
    return serve(a.port, tools, Path(a.out))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="gpudoc", description="Evidence-based reports on used GPUs.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("inspect", help="Read a GPU's identity, settings, and error history. Does not stress the card.")
    i.add_argument("--out", default="gpudoc-runs", help="Folder for results")
    i.add_argument("--redact", action="store_true", help="Show the redacted report")
    i.add_argument("--ssh", metavar="USER@HOST", help="Inspect a remote machine over SSH key login")
    i.add_argument("--from-capture", metavar="DIR", help="Re-parse saved real output")
    i.set_defaults(func=cmd_inspect)
    t = sub.add_parser("test", help="Draft: run memory, compute and AI stress tests on one card with safety stops. Asks for confirmation.")
    t.add_argument("--tool-path", help="Path to memtest_vulkan, for the memory test")
    t.add_argument("--gpu-burn", help="Path to gpu_burn (gpu_burn.exe on Windows), to add a compute stress test that checks its results")
    t.add_argument("--burn-seconds", type=int, default=300, help="How long gpu-burn runs. Default 300")
    t.add_argument("--gpu-fryer", help="Path to gpu-fryer, to add a load and throttling test (Linux only)")
    t.add_argument("--fryer-seconds", type=int, default=300, help="How long gpu-fryer runs. Default 300")
    t.add_argument("--dcgm", nargs="?", const="dcgmi", help="Run Nvidia DCGM diagnostics first (Linux; optional path to dcgmi)")
    t.add_argument("--localscore", help="Path to the LocalScore binary. Results are never uploaded; on Linux it also runs with no network")
    t.add_argument("--localscore-model", help="GGUF model for LocalScore, such as its 1B reference model")
    t.add_argument("--wattever", help="Path to Wattever's folder, to add its speed and power benchmark (uses --model)")
    t.add_argument("--llama-server", help="Path to llama.cpp's llama-server, for --wattever")
    t.add_argument("--dcgm-level", type=int, default=1, help="DCGM run level. GeForce cards support level 1 only. Default 1")
    t.add_argument("--gpu", help="Card to test, by nvidia-smi index or PCI bus ID such as 02:00.0, or 'all' for each card in turn. "
                                 "Required when more than one GPU is installed")
    t.add_argument("--llama-bench", help="Path to llama-bench, to add an AI workload")
    t.add_argument("--model", help="Path to the GGUF model for llama-bench")
    t.add_argument("--out", default="gpudoc-runs", help="Folder for results")
    t.add_argument("--temp-limit", type=int, help="Lower the stop temperature in C. Default: 5 C below the card's own slowdown or max operating limit, or 85 if it reports none")
    t.add_argument("--max-seconds", type=int, default=420, help="Stop after this long, reported as inconclusive")
    t.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    t.set_defaults(func=cmd_test)
    s = sub.add_parser("sweep", help="Draft: measure output per watt at several power limits on one card. Asks for confirmation.")
    s.add_argument("--tool-path", required=True, help="Path to memtest_vulkan")
    s.add_argument("--gpu", help="Card, by nvidia-smi index or PCI bus ID. Required when more than one GPU is installed")
    s.add_argument("--limits", required=True, help="Power limits in watts, such as 70,85,100,120")
    s.add_argument("--seconds", type=int, default=75, help="Seconds per limit; 75 gives one full 30-second reading after warm-up")
    s.add_argument("--out", default="gpudoc-runs", help="Folder for results")
    s.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    s.set_defaults(func=cmd_sweep)
    u = sub.add_parser("tune", help="Draft: find the highest stable GPU clock offset on one card, step by step. Asks for confirmation.")
    u.add_argument("--gpu", help="Card, by nvidia-smi index or PCI bus ID. Required when more than one GPU is installed")
    u.add_argument("--gpu-burn", help="Path to gpu_burn (gpu_burn.exe on Windows), the workload that proves each step")
    u.add_argument("--tool-path", help="Path to memtest_vulkan, as the workload instead of gpu-burn")
    u.add_argument("--step", type=int, default=25, help="MHz added per step. Default 25")
    u.add_argument("--max-offset", type=int, default=150, help="Highest offset to try, in MHz. Default 150")
    u.add_argument("--seconds", type=int, default=60, help="Seconds per step. Default 60")
    u.add_argument("--confirm-seconds", type=int, default=300, help="Length of the confirmation run. Default 300")
    u.add_argument("--reset", action="store_true", help="Only return the card's clock offsets to stock, then exit")
    u.add_argument("--out", default="gpudoc-runs", help="Folder for results")
    u.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    u.set_defaults(func=cmd_tune)
    w = sub.add_parser("serve", help="Draft: open a local web page to see cards, run tests and browse results. This machine only.")
    w.add_argument("--port", type=int, default=8740, help="Port on 127.0.0.1. Default 8740")
    w.add_argument("--tools", help="JSON file of tool paths, keyed like the test options (tool_path, gpu_burn, model, ...). "
                                   "Default: gpudoc-tools.json in the current folder, if present")
    w.add_argument("--out", default="gpudoc-runs", help="Results folder, shared with gpudoc test")
    w.set_defaults(func=cmd_serve)
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
