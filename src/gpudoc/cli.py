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
    from .testing import LlamaBench, MemtestVulkan, run_suite
    adapters = [MemtestVulkan(a.tool_path)]
    if a.llama_bench or a.model:
        if not (a.llama_bench and a.model):
            print("--llama-bench and --model must be used together.")
            return 3
        adapters.append(LlamaBench(a.llama_bench, a.model))
    print("These tests stress the GPU and raise its temperature, and they could expose or worsen an existing fault.")
    print(f"Tools: {', '.join(x.id for x in adapters)}. Stop limit: {a.temp_limit or 'automatic'} C. Time limit per tool: {a.max_seconds} s.")
    if not a.yes and input("Type YES to continue: ").strip() != "YES":
        print("Cancelled. Nothing was run.")
        return 3
    d = Path(a.out) / ("test-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    suite = run_suite(adapters, d, max_seconds=a.max_seconds, temp_limit=a.temp_limit)
    print(f"\nOverall: {suite['state']}")
    for step in suite["steps"]:
        print(f"\n{step.get('tool_id', 'tool')}: {step['state']}")
        for f in step["findings"]:
            print(f"- [{f['state']}] {f['rule']}: {f['text']}")
        print(f"Summary: {step.get('summary')}")
    if suite["skipped"]:
        print(f"\nNot run: {', '.join(suite['skipped'])}")
    print(f"Saved to {d}")
    return {"PASS": 0, "ATTENTION": 0, "INCONCLUSIVE": 2, "FAIL": 1}[suite["state"]]


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
    t = sub.add_parser("test", help="Draft: run a memory stress test with safety stops. Asks for confirmation.")
    t.add_argument("--tool-path", required=True, help="Path to memtest_vulkan")
    t.add_argument("--llama-bench", help="Path to llama-bench, to add an AI workload")
    t.add_argument("--model", help="Path to the GGUF model for llama-bench")
    t.add_argument("--out", default="gpudoc-runs", help="Folder for results")
    t.add_argument("--temp-limit", type=int, help="Stop temperature in C (default: 85, or lower if the card requires it)")
    t.add_argument("--max-seconds", type=int, default=420, help="Stop after this long, reported as inconclusive")
    t.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    t.set_defaults(func=cmd_test)
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
