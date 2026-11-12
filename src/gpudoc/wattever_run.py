"""Runs one Wattever benchmark against a llama.cpp server on one card, then shuts both down.

Wattever (github.com/lpalbou/Wattever, MIT) measures an OpenAI-compatible endpoint; it doesn't run models itself.
This starts `llama-server` on the chosen device, starts Wattever's local helper without a browser, sends one
benchmark through Wattever's documented local API, waits for it, and prints the result file's path and summary
on a final line starting with "GPUDOC-WATTEVER ". Both servers listen on 127.0.0.1 only.

Standard library only, so it can run as its own process under GPUDoc's process guard.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PREFIX = "GPUDOC-WATTEVER "


def http(method: str, url: str, body: dict | None = None, timeout: float = 10.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "null")


def run_list(answer) -> list[dict]:
    """The run summaries from GET /api/runs, which may be a list or an object holding one."""
    if isinstance(answer, list):
        return [r for r in answer if isinstance(r, dict)]
    if isinstance(answer, dict):
        for key in ("runs", "items", "data"):
            if isinstance(answer.get(key), list):
                return [r for r in answer[key] if isinstance(r, dict)]
    return []


def wait_for(url: str, seconds: float, proc: subprocess.Popen, what: str):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{what} exited early with code {proc.returncode}")
        try:
            return http("GET", url, timeout=3)
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(1)
    raise RuntimeError(f"{what} didn't answer at {url} within {seconds:.0f} s")


def stop(proc: subprocess.Popen | None):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--wattever", required=True, help="Wattever's folder (the one holding the wattever package)")
    p.add_argument("--llama-server", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--device", help="llama.cpp device, such as Vulkan1; omit with one card")
    p.add_argument("--gpu-index", type=int, default=0, help="nvidia-smi index of the card, for Wattever's records")
    p.add_argument("--llama-port", type=int, default=8790)
    p.add_argument("--wattever-port", type=int, default=8713)
    p.add_argument("--sizes", default="512,4000", help="Prompt sizes in tokens")
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--context", type=int, default=8192)
    p.add_argument("--max-wait", type=int, default=1500, help="Seconds to wait for the benchmark")
    a = p.parse_args()

    llama = wattever = None
    out = {"status": "not_started"}

    def on_signal(signum, _frame):
        raise KeyboardInterrupt(signal.Signals(signum).name)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, on_signal)
    try:
        cmd = [a.llama_server, "-m", a.model, "-ngl", "99", "-c", str(a.context), "--host", "127.0.0.1", "--port", str(a.llama_port)]
        if a.device:
            cmd += ["-dev", a.device]
        print("starting:", " ".join(cmd), flush=True)
        llama = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stdout, stdin=subprocess.DEVNULL)
        wait_for(f"http://127.0.0.1:{a.llama_port}/health", 300, llama, "llama-server")
        models = http("GET", f"http://127.0.0.1:{a.llama_port}/v1/models")
        model_id = models["data"][0]["id"]
        print("llama-server ready, model:", model_id, flush=True)

        env = dict(os.environ, GPU_BENCH_NO_BROWSER="1", GPU_BENCH_PORT=str(a.wattever_port))
        wattever = subprocess.Popen([sys.executable, "-m", "wattever.server"], cwd=a.wattever, env=env, stdout=sys.stdout,
                                    stderr=sys.stdout, stdin=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{a.wattever_port}"
        version = wait_for(f"{base}/api/version", 60, wattever, "Wattever")
        print("Wattever ready:", json.dumps(version)[:300], flush=True)
        before = {r.get("id") for r in run_list(http("GET", f"{base}/api/runs"))}
        config = {"provider": "openai", "endpoint_base_url": f"http://127.0.0.1:{a.llama_port}/v1", "endpoint_inference_local": True,
                  "models": [model_id], "sizes": [int(x) for x in a.sizes.split(",")], "concurrency_levels": [1],
                  "max_tokens": a.max_tokens, "repeats": a.repeats, "gpu_index": a.gpu_index, "temperature": 0,
                  "reproducibility": {"engine": "llama.cpp llama-server", "context_tokens": a.context}}
        print("starting benchmark:", json.dumps(config), flush=True)
        print("start answered:", json.dumps(http("POST", f"{base}/api/bench/start", config, timeout=60))[:500], flush=True)
        deadline, status = time.monotonic() + a.max_wait, {}
        while time.monotonic() < deadline:
            time.sleep(5)
            status = http("GET", f"{base}/api/status") or {}
            if not status.get("running") and not status.get("active"):
                break
        print("final status:", json.dumps(status)[:800], flush=True)
        runs = run_list(http("GET", f"{base}/api/runs"))
        new = [r for r in runs if r.get("id") not in before]
        out = {"status": "timed_out" if time.monotonic() >= deadline else "finished", "model_id": model_id, "runs": new[:3]}
        if new:
            rid = new[0]["id"]
            path = Path(a.wattever) / "results" / "runs" / f"{rid}.json"
            out.update(run_id=rid, file=str(path) if path.exists() else None)
    except KeyboardInterrupt as e:
        out = {"status": "interrupted", "signal": str(e)}
    except Exception as e:  # noqa: BLE001 - every failure is reported on the result line
        out = {"status": "error", "error": f"{type(e).__name__}: {e}"[:500]}
    finally:
        if wattever is not None and wattever.poll() is None:
            try:
                http("POST", f"http://127.0.0.1:{a.wattever_port}/api/shutdown", {}, timeout=5)
                wattever.wait(timeout=15)
            except Exception:  # noqa: BLE001
                pass
        stop(wattever)
        stop(llama)
    print(PREFIX + json.dumps(out), flush=True)
    return 0 if out.get("status") == "finished" else 1


if __name__ == "__main__":
    sys.exit(main())
