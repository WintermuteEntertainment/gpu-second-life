"""Local web page for GPUDoc: see the cards, start a test, watch it live, and browse results.

Started with `gpudoc serve`. Standard library only. It listens on 127.0.0.1 only, so other machines can't reach it.
A test runs as its own `gpudoc test` process, so it goes through exactly the same code and safety stops as the
command line: the page never stresses a card by any other route. Stop sends that process the same interrupt as
Ctrl+C (Ctrl+Break on Windows), and the run is recorded as interrupted.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import __version__
from .inspect_core import LocalRunner, inspect
from .testing import describe_gpu, temp_limit_for

HOST = "127.0.0.1"
DEFAULT_PORT = 8740

# Each tool the page can run, with the `gpudoc test` flags it needs from the tools file.
TOOLS = {
    "dcgm": {"label": "DCGM diagnostics (level 1)", "flags": [("--dcgm", "dcgm")]},
    "memtest": {"label": "memtest_vulkan (memory)", "flags": [("--tool-path", "tool_path")]},
    "gpu_burn": {"label": "gpu-burn (compute, error check)", "flags": [("--gpu-burn", "gpu_burn")]},
    "gpu_fryer": {"label": "gpu-fryer (load and throttling)", "flags": [("--gpu-fryer", "gpu_fryer")]},
    "llama_bench": {"label": "llama-bench (AI speed)", "flags": [("--llama-bench", "llama_bench"), ("--model", "model")]},
    "localscore": {"label": "LocalScore (AI score, never uploaded)", "flags": [("--localscore", "localscore"), ("--localscore-model", "localscore_model")]},
    "wattever": {"label": "Wattever (AI speed and power)", "flags": [("--wattever", "wattever"), ("--llama-server", "llama_server"), ("--model", "model")]},
}
WARNING = "These tests stress the GPU and raise its temperature, and they could expose or worsen an existing fault."


def load_tools(path: Path | None) -> dict:
    """The tools file: a JSON object of paths, keyed like the `gpudoc test` options (tool_path, gpu_burn, model, ...)."""
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}


def available_tools(config: dict) -> list[dict]:
    out = []
    for tid, t in TOOLS.items():
        missing = [key for _, key in t["flags"] if key not in config]
        out.append({"id": tid, "label": t["label"], "available": not missing, "missing": missing})
    return out


def test_args(config: dict, tools: list[str], gpu: str, out_dir: Path) -> list[str]:
    """`gpudoc test` arguments for the chosen tools. Raises ValueError for an unknown or unconfigured tool."""
    args, seen = ["test", "--gpu", gpu, "--out", str(out_dir), "--max-seconds", "900", "--yes"], set()
    for tid in tools:
        if tid not in TOOLS:
            raise ValueError(f"unknown tool '{tid}'")
        for flag, key in TOOLS[tid]["flags"]:
            if key not in config:
                raise ValueError(f"{TOOLS[tid]['label']} isn't set up: '{key}' is missing from the tools file")
            if flag not in seen:
                args += [flag, config[key]]
                seen.add(flag)
    if not tools:
        raise ValueError("choose at least one tool")
    return args


def card_summary(report: dict) -> list[dict]:
    out = []
    for g in report["gpus"]:
        f, d = g["fields"], g["details"]
        val = lambda k: (f.get(k) or {}).get("value")  # noqa: E731
        out.append({"index": g["index"], "label": describe_gpu(g), "name": val("name"), "bus": d.get("pci_bus_id"),
                    "driver": val("driver_version"), "temperature": val("temperature_gpu"), "power": val("power_draw"),
                    "memory_total": val("memory_total"), "pcie": f"x{val('pcie_width_current')} of x{val('pcie_width_max')}",
                    "architecture": d.get("architecture"), "stop_limit": temp_limit_for(d, None),
                    "notes": g.get("notes", [])})
    return out


def safe_child(base: Path, rel: str) -> Path | None:
    """A path inside base, or None if rel tries to leave it."""
    p = (base / unquote(rel)).resolve()
    try:
        p.relative_to(base.resolve())
    except ValueError:
        return None
    return p


def list_runs(out_dir: Path) -> list[dict]:
    runs = []
    for d in sorted(out_dir.glob("test-*"), reverse=True):
        suites = sorted(d.glob("suite.json")) + sorted(d.glob("*/suite.json"))
        cards = []
        for s in suites:
            try:
                data = json.loads(s.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            cards.append({"folder": str(s.parent.relative_to(out_dir)).replace("\\", "/"), "state": data.get("state"),
                          "steps": [{"tool": st.get("tool_id"), "state": st.get("state"), "summary": st.get("summary", {}),
                                     "findings": st.get("findings", []), "gpu": st.get("gpu_name"), "bus": st.get("gpu_bus_id")}
                                    for st in data.get("steps", [])], "skipped": data.get("skipped", [])})
        runs.append({"name": d.name, "cards": cards, "complete": bool(cards)})
    return runs


def latest_telemetry(run_dir: Path, limit: int = 120) -> dict:
    """The newest step's telemetry in a running test, for the live view."""
    files = sorted(run_dir.rglob("telemetry.jsonl"), key=lambda p: p.stat().st_mtime) if run_dir.exists() else []
    if not files:
        return {"step": None, "samples": []}
    f = files[-1]
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    samples = []
    for line in lines:
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return {"step": str(f.parent.relative_to(run_dir)).replace("\\", "/"), "samples": samples}


class Runner:
    """Starts one `gpudoc test` process at a time and stops it with the same interrupt as Ctrl+C."""

    def __init__(self, out_dir: Path):
        self.out_dir, self.lock, self.proc, self.info = out_dir, threading.Lock(), None, {}

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, args: list[str]) -> dict:
        with self.lock:
            if self.running():
                return {"error": "A test is already running. Wait for it to finish, or stop it first."}
            before = {p.name for p in self.out_dir.glob("test-*")}
            log = self.out_dir / f"web-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
            pkg_parent = str(Path(__file__).resolve().parent.parent)
            code = f"import sys; sys.path.insert(0, {pkg_parent!r}); from gpudoc.cli import main; sys.exit(main())"
            cmd = [sys.executable, "-c", code] + args
            linux, win = sys.platform.startswith("linux"), os.name == "nt"
            kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if win else {"start_new_session": True}
            if linux:
                from .testing import _die_with_parent
                kw["preexec_fn"] = _die_with_parent  # if the page's server dies, the test stops too
            fh = open(log, "wb")
            # Linux's "die with parent" signal is tied to the thread that starts the process, not the whole server, and
            # each web request runs in a thread that ends right after answering. Found on Noodlecart, 2026-11-13: the
            # first test started from the page was killed at once. So a thread that lives exactly as long as the test
            # starts it and then waits for it.
            started, box = threading.Event(), {}

            def launch():
                try:
                    box["proc"] = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
                except OSError as e:
                    box["error"] = str(e)
                started.set()
                if "proc" in box:
                    box["proc"].wait()

            threading.Thread(target=launch, name="gpudoc-test", daemon=True).start()
            started.wait(timeout=30)
            if "proc" not in box:
                fh.close()
                return {"error": f"The test couldn't be started: {box.get('error', 'timed out')}"}
            self.proc = box["proc"]
            if win:
                from .testing import kill_with_parent_windows
                kill_with_parent_windows(self.proc)
            self.info = {"started": dt.datetime.now().isoformat(timespec="seconds"), "log": log, "before": before,
                         "args": args, "stopping": False, "fh": fh}
            return {"started": self.info["started"]}

    def run_dir(self) -> Path | None:
        if not self.info:
            return None
        new = sorted(p for p in self.out_dir.glob("test-*") if p.name not in self.info["before"])
        return new[-1] if new else None

    def stop(self) -> dict:
        with self.lock:
            if not self.running():
                return {"error": "No test is running."}
            if os.name == "nt":
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.proc.send_signal(signal.SIGINT)
            self.info["stopping"] = True
            return {"stopping": True}

    def status(self) -> dict:
        if not self.info:
            return {"running": False}
        log = self.info["log"]
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        rd = self.run_dir()
        out = {"running": self.running(), "started": self.info["started"], "stopping": self.info["stopping"],
               "exit_code": None if self.running() else self.proc.returncode, "log_tail": text.splitlines()[-40:],
               "run": rd.name if rd else None}
        out.update(latest_telemetry(rd) if rd else {"step": None, "samples": []})
        if not self.running() and not self.info["fh"].closed:
            self.info["fh"].close()
        return out


class Handler(BaseHTTPRequestHandler):
    server_version = f"GPUDoc/{__version__}"

    def log_message(self, fmt, *a):  # keep the console quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data, default=str).encode(), "application/json")

    def _host_ok(self) -> bool:
        # Refuses requests whose Host isn't this machine's loopback address, so a web page elsewhere can't reach
        # the server by pointing a domain name at 127.0.0.1 (DNS rebinding).
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        o = urlparse(origin)
        return o.hostname in ("127.0.0.1", "localhost", "::1") and o.port == self.server.server_port

    def do_GET(self):
        if not self._host_ok():
            return self._json({"error": "forbidden host"}, 403)
        app, path = self.server.app, urlparse(self.path).path
        if path == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if path == "/api/info":
            return self._json({"version": __version__, "warning": WARNING, "tools": available_tools(app["config"]),
                               "tools_file": str(app["tools_file"]) if app["tools_file"] else None, "out": str(app["out"])})
        if path == "/api/cards":
            report, _ = inspect(LocalRunner())
            return self._json({"cards": card_summary(report), "driver": report.get("driver_version"), "errors": report.get("errors", [])})
        if path == "/api/status":
            return self._json(app["runner"].status())
        if path == "/api/runs":
            return self._json({"runs": list_runs(app["out"])})
        if path.startswith("/runs/"):
            p = safe_child(app["out"], path[len("/runs/"):])
            if p is None or not p.is_file() or p.suffix not in (".json", ".jsonl", ".txt", ".md", ".log"):
                return self._json({"error": "not found"}, 404)
            return self._send(200, p.read_bytes(), "text/plain; charset=utf-8")
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._host_ok() or not self._origin_ok():
            return self._json({"error": "forbidden origin"}, 403)
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self._json({"error": "send JSON"}, 415)
        app, path = self.server.app, urlparse(self.path).path
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 65536)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "bad JSON"}, 400)
        if path == "/api/run":
            if body.get("confirm") != "YES":
                return self._json({"error": "Confirmation missing. Nothing was run."}, 400)
            gpu = str(body.get("gpu", "")).strip()
            if not gpu:
                return self._json({"error": "Choose a card."}, 400)
            try:
                args = test_args(app["config"], list(body.get("tools") or []), gpu, app["out"])
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            r = app["runner"].start(args)
            return self._json(r, 409 if "error" in r else 200)
        if path == "/api/stop":
            r = app["runner"].stop()
            return self._json(r, 409 if "error" in r else 200)
        return self._json({"error": "not found"}, 404)


def make_server(port: int, tools_file: Path | None, out: Path) -> ThreadingHTTPServer:
    out.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    httpd.daemon_threads = True
    httpd.app = {"config": load_tools(tools_file), "tools_file": tools_file, "out": out.resolve(), "runner": Runner(out.resolve())}
    return httpd


def serve(port: int, tools_file: Path | None, out: Path) -> int:
    httpd = make_server(port, tools_file, out)
    print(f"GPUDoc page: http://{HOST}:{httpd.server_port}/  (this machine only)")
    print(f"Tools file: {tools_file or 'none'}. Results folder: {httpd.app['out']}. Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner = httpd.app["runner"]
        if runner.running():
            print("Stopping the running test...")
            runner.stop()
            try:
                runner.proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                print("The test didn't stop within 120 s; check for leftover processes.")
        httpd.server_close()
    return 0


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GPUDoc</title><style>
:root{color-scheme:light dark;--bg:#f5f6f8;--card:#fff;--text:#1c2128;--muted:#5d6673;--line:#dfe3e8;--accent:#3a5bc7;
--good:#176b3a;--good-bg:#e3f4ea;--warn:#8a5a00;--warn-bg:#fdf1d7;--bad:#a4262c;--bad-bg:#fbe5e6;--na:#59626e;--na-bg:#eceef1}
@media (prefers-color-scheme:dark){:root{--bg:#14171b;--card:#1d2127;--text:#e8eaed;--muted:#a1a9b4;--line:#333942;--accent:#9db2f5;
--good:#6fd39a;--good-bg:#17352a;--warn:#e7bd63;--warn-bg:#3b2f13;--bad:#f09a9e;--bad-bg:#44201f;--na:#aab2bd;--na-bg:#2a2f36}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 48px}h1{font-size:1.5rem;margin:0}h2{font-size:1.1rem;margin:0 0 10px}
.meta{color:var(--muted);font-size:.85rem;margin:2px 0 18px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px}
.gpu{border:1px solid var(--line);border-radius:8px;padding:10px 12px;cursor:pointer;display:block}.gpu input{margin-right:8px;accent-color:var(--accent)}
.gpu.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}.gpu small{display:block;color:var(--muted)}
.tools label{display:block;margin:4px 0}.tools .off{color:var(--muted)}button{font:inherit;padding:7px 16px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--text);cursor:pointer}
button.go{background:var(--accent);color:#fff;border-color:var(--accent)}button.stop{background:var(--bad);color:#fff;border-color:var(--bad)}button:disabled{opacity:.5;cursor:default}
.warnbox{border-left:4px solid var(--warn);background:var(--warn-bg);padding:10px 14px;border-radius:6px;margin:12px 0}
.chip{display:inline-block;padding:1px 8px;border-radius:99px;font-size:.75rem;font-weight:600}
.PASS{color:var(--good);background:var(--good-bg)}.ATTENTION{color:var(--warn);background:var(--warn-bg)}.FAIL{color:var(--bad);background:var(--bad-bg)}.INCONCLUSIVE,.NOTE{color:var(--na);background:var(--na-bg)}
table{width:100%;border-collapse:collapse;font-size:.875rem}td,th{padding:5px 6px;border-top:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:10px 0}.tile{border:1px solid var(--line);border-radius:8px;padding:8px 10px}.tile b{display:block;font-size:1.2rem}.tile span{font-size:.75rem;color:var(--muted)}
canvas{width:100%;height:160px;border:1px solid var(--line);border-radius:8px}pre{white-space:pre-wrap;font-size:.75rem;max-height:220px;overflow:auto;background:var(--bg);padding:8px;border-radius:6px}
details{border-top:1px solid var(--line);padding:6px 0}summary{cursor:pointer}.err{color:var(--bad)}.muted{color:var(--muted)}
</style></head><body><main>
<h1>GPUDoc</h1><div class="meta" id="meta">Loading...</div>
<section class="card"><h2>Cards</h2><div class="cards" id="cards">Reading cards...</div></section>
<section class="card"><h2>Run a test</h2><div class="tools" id="tools"></div>
<div class="warnbox" id="warn"></div><div id="limits" class="muted"></div>
<p><label><input type="checkbox" id="ok"> I understand, and the card is ready to be stressed.</label></p>
<button class="go" id="start" disabled>Start test</button> <button class="stop" id="stop" disabled>Stop</button> <span id="msg"></span></section>
<section class="card" id="livecard"><h2>Live</h2><div id="livestate" class="muted">No test running.</div>
<div class="tiles" id="tiles"></div><canvas id="chart" width="960" height="160"></canvas><details><summary>Output</summary><pre id="log"></pre></details></section>
<section class="card"><h2>Results</h2><div id="runs">Loading...</div></section>
</main><script>
const $=id=>document.getElementById(id);let cards=[],info={},sel=null,poll=null;
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(p,body){const r=await fetch(p,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{});return [r.status,await r.json()]}
function chip(s){return `<span class="chip ${esc(s)}">${esc(s)}</span>`}
function refreshStart(){const tools=[...document.querySelectorAll(".tools input:checked")];$("start").disabled=!(sel&&tools.length&&$("ok").checked)||!!poll}
function renderCards(){$("cards").innerHTML=cards.length?cards.map(c=>`<label class="gpu ${sel===c.bus?"sel":""}"><input type="radio" name="gpu" value="${esc(c.bus)}" ${sel===c.bus?"checked":""}>
<b>${esc(c.name)}</b><small>${esc(c.bus)} · ${esc(c.architecture)} · PCIe ${esc(c.pcie)} · driver ${esc(c.driver)}</small>
<small>${esc(c.temperature)} C now · ${esc(c.power)} W · ${esc(Math.round(c.memory_total||0))} MiB · stop limit ${esc(c.stop_limit)} C</small></label>`).join(""):'<span class="err">No GPU was detected.</span>';
document.querySelectorAll('input[name=gpu]').forEach(i=>i.onchange=()=>{sel=i.value;renderCards();limits();refreshStart()})}
function limits(){const c=cards.find(c=>c.bus===sel);$("limits").textContent=c?`Card: ${c.label}. GPUDoc stops the test at ${c.stop_limit} C. Time limit per tool: 900 s.`:"Choose a card."}
async function load(){const [,i]=await api("/api/info");info=i;$("meta").textContent=`Version ${i.version} · results in ${i.out} · tools file ${i.tools_file||"none"} · this machine only`;
$("warn").textContent=i.warning;$("tools").innerHTML=i.tools.map(t=>`<label class="${t.available?"":"off"}"><input type="checkbox" value="${t.id}" ${t.available?"":"disabled"}> ${esc(t.label)}${t.available?"":` <small>(not set up: ${esc(t.missing.join(", "))})</small>`}</label>`).join("");
document.querySelectorAll(".tools input").forEach(i=>i.onchange=refreshStart);$("ok").onchange=refreshStart;
const [,c]=await api("/api/cards");cards=c.cards;if(cards.length===1)sel=cards[0].bus;renderCards();limits();refreshStart();loadRuns();status()}
$("start").onclick=async()=>{const tools=[...document.querySelectorAll(".tools input:checked")].map(i=>i.value);$("msg").textContent="Starting...";
const [code,r]=await api("/api/run",{gpu:sel,tools,confirm:"YES"});$("msg").innerHTML=code===200?"Started.":`<span class="err">${esc(r.error)}</span>`;if(code===200){$("ok").checked=false;status()}};
$("stop").onclick=async()=>{const [code,r]=await api("/api/stop",{});$("msg").innerHTML=code===200?"Stopping; the run is recorded as interrupted.":`<span class="err">${esc(r.error)}</span>`};
function draw(s){const cv=$("chart"),x=cv.getContext("2d"),W=cv.width,H=cv.height;x.clearRect(0,0,W,H);if(s.length<2)return;
const css=getComputedStyle(document.documentElement);const series=[["temperature_gpu",100,css.getPropertyValue("--bad")],["power_draw",Math.max(150,...s.map(v=>v.power_draw||0)),css.getPropertyValue("--accent")]];
const t0=s[0].elapsed||0,t1=s[s.length-1].elapsed||1;for(const [k,mx,col] of series){x.strokeStyle=col.trim();x.lineWidth=2;x.beginPath();s.forEach((v,i)=>{const px=(v.elapsed-t0)/(t1-t0||1)*(W-10)+5,py=H-5-(v[k]||0)/mx*(H-10);i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke()}
x.fillStyle=css.getPropertyValue("--muted");x.font="12px system-ui";x.fillText("temperature (red, 0-100 C)   power (blue)",8,14)}
async function status(){const [,s]=await api("/api/status");const live=s.running;$("stop").disabled=!live;
if(live&&!poll)poll=setInterval(status,3000);if(!live&&poll){clearInterval(poll);poll=null;loadRuns();api("/api/cards").then(([,c])=>{cards=c.cards;renderCards()})}
refreshStart();if(!s.started){return}
$("livestate").innerHTML=live?`Running since ${esc(s.started)}${s.stopping?" · stopping":""} · step: ${esc(s.step||"starting")}`:`Last test finished (exit code ${esc(s.exit_code)}) · ${esc(s.run||"")}`;
const v=(s.samples||[]).slice(-1)[0]||{};$("tiles").innerHTML=[["temperature_gpu","C","Temperature"],["power_draw","W","Power"],["clock_gpu","MHz","GPU clock"],["memory_used","MiB","Memory used"],["gpu_util","%","Load"]].map(([k,u,l])=>`<div class="tile"><b>${v[k]??"-"} ${u}</b><span>${l}</span></div>`).join("");
draw(s.samples||[]);$("log").textContent=(s.log_tail||[]).join("\n")}
async function loadRuns(){const [,r]=await api("/api/runs");$("runs").innerHTML=r.runs.length?r.runs.slice(0,30).map(run=>`<details><summary><b>${esc(run.name)}</b> ${run.cards.map(c=>chip(c.state)).join(" ")||'<span class="muted">no result yet</span>'}</summary>
${run.cards.map(c=>`<p><b>${esc(c.steps[0]?.gpu||c.folder)}</b> ${esc(c.steps[0]?.bus||"")} ${chip(c.state)}${c.skipped.length?` <span class="muted">not run: ${esc(c.skipped.join(", "))}</span>`:""}</p>
<table><tr><th>Tool</th><th>Result</th><th>Key figures</th><th>Findings</th></tr>${c.steps.map(st=>`<tr><td>${esc(st.tool)}</td><td>${chip(st.state)}</td><td>${figures(st.summary)}</td>
<td>${st.findings.filter(f=>f.rule!=="LIM-001").map(f=>`${chip(f.state)} ${esc(f.rule)}: ${esc(f.text)}`).join("<br>")}</td></tr>`).join("")}</table>`).join("")}</details>`).join(""):'<span class="muted">No results yet.</span>'}
function figures(s){const k=[["gflops","Gflop/s"],["generation_tokens_per_second","gen tok/s"],["prompt_tokens_per_second","prompt tok/s"],["peak_temp","C peak"],["avg_power_under_load_w","W avg"],["avg_gpu_clock_under_load_mhz","MHz avg"],["memory_coverage_percent","% VRAM"]];
return k.filter(([n])=>s[n]!=null).map(([n,u])=>`${esc(typeof s[n]==="number"?Math.round(s[n]*10)/10:s[n])} ${u}`).join(" · ")}
load();
</script></body></html>"""
