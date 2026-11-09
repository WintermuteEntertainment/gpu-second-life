"""Command line entry point."""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
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
    from .testing import LlamaBench, MemtestVulkan, describe_gpu, run_suite, select_gpu, temp_limit_for
    adapters = [MemtestVulkan(a.tool_path)]
    if a.llama_bench or a.model:
        if not (a.llama_bench and a.model):
            print("--llama-bench and --model must be used together.")
            return 3
        adapters.append(LlamaBench(a.llama_bench, a.model))
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
    if len(report["gpus"]) > 1 and any(not getattr(x, "reports_device", False) for x in adapters):
        print("Nothing was run. llama-bench can't yet be confirmed to use only the selected card when several GPUs are installed.")
        return 3
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
    t = sub.add_parser("test", help="Draft: run a memory stress test on one card with safety stops. Asks for confirmation.")
    t.add_argument("--tool-path", required=True, help="Path to memtest_vulkan")
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
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
