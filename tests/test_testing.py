"""Rules and parsers are tested with real memtest_vulkan logs and telemetry from Noodlecart."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from gpudoc.inspect_core import CaptureRunner, inspect, parse_valid_fields
import json

from gpudoc.testing import (DcgmDiag, Evidence, GpuBurn, GpuFryer, LlamaBench, LocalScore, Wattever, MemtestVulkan, load_findings, strayed, track_load, combine, device_check, energy_wh, evaluate, memtest_label_for,
                            parse_bus_id, parse_xid, resolve_sample_fields, select_gpu, stop_and_confirm, temp_limit_for,
                            wait_until_idle)

CAPTURES = Path(__file__).parent / "captures"
ADAPTER = MemtestVulkan("memtest_vulkan")


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed process that hasn't been reaped yet still answers; treat a zombie as gone.
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def load(name):
    folder = CAPTURES / name
    tool = ADAPTER.parse((folder / "stdout.txt").read_text(encoding="utf-8"))
    samples = []
    for line in (folder / "telemetry.csv").read_text(encoding="utf-8-sig").splitlines()[1:]:
        c = [x.strip() for x in line.split(",")]
        samples.append({"temperature_gpu": int(c[1]), "memory_used": int(c[5].split()[0]), "hw_thermal": c[7], "sw_thermal": c[8]})
    return tool, samples


def ev(tool, samples, total=6144.0, **kw):
    base = dict(tool=tool, samples=samples, stop={"stopped": True}, memory_total=total, driver_before="x", driver_after="x", driver_errors=0, temp_limit=85)
    base.update(kw)
    return Evidence(**base)


class RealLogs(unittest.TestCase):
    def test_1660_full_run_passes_with_coverage_note(self):
        tool, samples = load("memtest_gtx1660_full")
        self.assertTrue(tool["completed"])
        r = evaluate(ev(tool, samples))
        self.assertEqual(r["state"], "PASS")
        self.assertLess(r["summary"]["memory_coverage_percent"], 80)
        self.assertTrue(any(f["rule"] == "MEM-002" for f in r["findings"]))

    def test_1060_software_slowdown_is_a_note_not_attention(self):
        # The real 2026-11-06 run shows only software thermal slowdown (9 of 33 samples), no hardware slowdown.
        tool, samples = load("memtest_gtx1060_full")
        r = evaluate(ev(tool, samples, target_temp=83.0))
        self.assertEqual(r["state"], "PASS")
        note = [f for f in r["findings"] if f["rule"] == "THM-003"]
        self.assertEqual((len(note), note[0]["state"]), (1, "NOTE"))
        self.assertIn("9 of 33", note[0]["text"])
        self.assertIn("83 C", note[0]["text"])
        self.assertFalse(any(f["rule"] == "THM-002" for f in r["findings"]))
    # No real capture with hardware thermal slowdown exists yet, so THM-002 (ATTENTION) is unverified on real data.

    def test_progress_lines_are_not_a_pass(self):
        # The real bug: "Passed" progress lines ended a test after about 10 seconds.
        tool, samples = load("memtest_gtx1660_stopped_10s")
        self.assertFalse(tool["completed"])
        self.assertGreater(tool["iterations"], 0)
        self.assertEqual(evaluate(ev(tool, samples, stop_reason="time_limit"))["state"], "INCONCLUSIVE")

    def test_real_clean_logs_have_no_failure_lines(self):
        for name in ("memtest_gtx1660_full", "memtest_gtx1060_full"):
            self.assertEqual(load(name)[0]["failure_lines"], [], name)


class RealLlamaBench(unittest.TestCase):
    def test_real_results_parse(self):
        text = (CAPTURES / "llama_bench_gtx1660_vulkan" / "bench_1.jsonl").read_text(encoding="utf-8-sig")
        r = LlamaBench("llama-bench", "model.gguf").parse(text)
        self.assertTrue(r["completed"])
        self.assertGreater(r["generation_tokens_per_second"], 0)
        self.assertGreater(r["prompt_tokens_per_second"], r["generation_tokens_per_second"])
        self.assertEqual(r["backend"], "Vulkan")
        self.assertEqual(r["gpu_layers"], 99)

    def test_empty_output_is_not_complete(self):
        self.assertFalse(LlamaBench("x", "y").parse("")["completed"])


class RealIdleBehaviour(unittest.TestCase):
    def test_stale_reading_seen_on_real_run_does_not_block(self):
        # Real readings after memtest_vulkan stopped: 99%, then 83%, then 0%, with the tool gone.
        values = iter([99, 83, 0])
        r = wait_until_idle(lambda: next(values), sleep=lambda _: None)
        self.assertTrue(r["idle"])
        self.assertEqual(r["readings"], [99, 83, 0])

    def test_gpu_that_stays_busy_blocks(self):
        r = wait_until_idle(lambda: 99, attempts=3, sleep=lambda _: None)
        self.assertFalse(r["idle"])


class RealEnergy(unittest.TestCase):
    def test_energy_from_real_telemetry(self):
        samples = []
        for line in (CAPTURES / "memtest_gtx1660_full" / "telemetry.csv").read_text(encoding="utf-8-sig").splitlines()[1:]:
            c = [x.strip() for x in line.split(",")]
            samples.append({"elapsed": int(c[0]), "power_draw": float(c[3].split()[0])})
        wh = energy_wh(samples)
        self.assertGreater(wh, 7)
        self.assertLess(wh, 10)

    def test_too_few_readings_give_no_number(self):
        self.assertIsNone(energy_wh([]))


class SuiteState(unittest.TestCase):
    def test_worst_step_wins(self):
        self.assertEqual(combine([{"state": "PASS"}, {"state": "ATTENTION"}]), "ATTENTION")
        self.assertEqual(combine([{"state": "PASS"}, {"state": "FAIL"}, {"state": "INCONCLUSIVE"}]), "FAIL")

    def test_empty_suite_proves_nothing(self):
        self.assertEqual(combine([]), "INCONCLUSIVE")


class EvidenceRules(unittest.TestCase):
    def setUp(self):
        self.tool, self.samples = load("memtest_gtx1660_full")

    def test_unconfirmed_stop_cannot_pass(self):
        self.assertEqual(evaluate(ev(self.tool, self.samples, stop={"stopped": False}))["state"], "INCONCLUSIVE")

    def test_driver_change_cannot_pass(self):
        self.assertEqual(evaluate(ev(self.tool, self.samples, driver_after="y"))["state"], "INCONCLUSIVE")

    def test_no_telemetry_cannot_pass(self):
        self.assertEqual(evaluate(ev(self.tool, []))["state"], "INCONCLUSIVE")

    def test_uncollected_driver_log_is_disclosed(self):
        r = evaluate(ev(self.tool, self.samples, driver_errors=None))
        self.assertTrue(any(f["rule"] == "DRV-002" for f in r["findings"]))


class RealProcessControl(unittest.TestCase):
    def test_kill_is_confirmed_on_a_real_process(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        r = stop_and_confirm(p)
        self.assertTrue(r["stopped"])
        self.assertIsNotNone(p.poll())

    def test_child_process_is_stopped_with_its_parent(self):
        with tempfile.TemporaryDirectory() as d:
            pid_file = Path(d) / "child.pid"
            code = ("import subprocess,sys,time;"
                    "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
                    f"open(r'{pid_file}','w').write(str(c.pid));time.sleep(60)")
            p = subprocess.Popen([sys.executable, "-c", code], start_new_session=sys.platform != "win32")
            for _ in range(100):
                if pid_file.exists() and pid_file.read_text():
                    break
                time.sleep(0.1)
            child = pid_file.read_text()
            self.assertTrue(stop_and_confirm(p)["stopped"])
            time.sleep(1)
            self.assertFalse(alive(int(child)))

    def test_tool_dies_when_gpudoc_is_killed_outright(self):
        # A real parent process starts a real child through start_tool, then the parent alone is killed.
        # Windows uses a job object, Linux uses PR_SET_PDEATHSIG. Either way the child must not survive.
        with tempfile.TemporaryDirectory() as d:
            info = Path(d) / "child.txt"
            src = Path(__file__).parent.parent / "src"
            code = (f"import sys,time; sys.path.insert(0, r'{src}'); from pathlib import Path; from gpudoc.testing import start_tool;"
                    "p,g=start_tool([sys.executable,'-c','import time; time.sleep(60)'], Path('.'), None, None);"
                    f"open(r'{info}','w').write(str(p.pid)+' '+g); time.sleep(60)")
            parent = subprocess.Popen([sys.executable, "-c", code])
            for _ in range(100):
                if info.exists() and info.read_text():
                    break
                time.sleep(0.1)
            child, guard = info.read_text().split()
            self.assertNotEqual(guard, "none")
            self.assertTrue(alive(int(child)))
            parent.kill()  # SIGKILL or TerminateProcess: no cleanup code in the parent can run
            parent.wait()
            for _ in range(50):
                if not alive(int(child)):
                    break
                time.sleep(0.1)
            self.assertFalse(alive(int(child)), f"child {child} outlived its killed parent (guard {guard})")

    @unittest.skipUnless(sys.platform.startswith("linux"), "the command-line match is Linux only")
    def test_shell_that_started_gpudoc_is_not_a_leftover(self):
        # Found in a real run on 2026-11-12: the launching shell's command line named every tool, so each one was
        # wrongly reported as left running. Here a real shell names a tool and runs the check as its child.
        code = ("import sys; sys.path.insert(0, %r); from gpudoc.testing import still_running; "
                "from gpudoc.inspect_core import LocalRunner; print(len(still_running('gpu_burn_marker_x', LocalRunner())))") % str(Path(__file__).parents[1] / "src")
        out = subprocess.run(["sh", "-c", f"{sys.executable} -c \"{code}\" # gpu_burn_marker_x"], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "0", out.stderr)

    def test_already_exited_process_is_reported(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        self.assertEqual(stop_and_confirm(p)["method"], "already_exited")


class RealFieldData(unittest.TestCase):
    def test_sample_fields_exist_on_the_real_driver(self):
        text = (CAPTURES / "gtx1660_driver61088_windows" / "help_query_gpu.txt").read_text(encoding="utf-8")
        self.assertEqual(len(resolve_sample_fields(parse_valid_fields(text))), 13)

    def test_stop_limit_comes_from_each_cards_reported_limits(self):
        # Real Mint capture: 1660 slowdown 93 C and max operating 91 C; 1060 slowdown 99 C, max operating N/A.
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660_gtx1060_driver58017804_mint"))
        gtx1660, gtx1060 = (g["details"] for g in report["gpus"])
        self.assertEqual((gtx1660["max_operating_temp"], gtx1060["max_operating_temp"]), (91.0, None))
        self.assertEqual(temp_limit_for(gtx1660, None), 86)
        self.assertEqual(temp_limit_for(gtx1060, None), 94)

    def test_requested_limit_can_only_lower_it(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660_gtx1060_driver58017804_mint"))
        gtx1060 = report["gpus"][1]["details"]
        self.assertEqual(temp_limit_for(gtx1060, 80), 80)
        self.assertEqual(temp_limit_for(gtx1060, 100), 94)

    def test_card_with_no_reported_limits_gets_the_default(self):
        self.assertEqual(temp_limit_for({}, None), 85)


class RealTwoGpuSelection(unittest.TestCase):
    """Real Mint capture with both cards on driver 580.178.04, 2026-11-08."""

    def setUp(self):
        self.report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660_gtx1060_driver58017804_mint"))
        self.gpus = self.report["gpus"]

    def test_capture_has_both_cards_on_their_buses(self):
        self.assertEqual([(g["fields"]["name"]["value"], g["details"]["pci_bus_id"]) for g in self.gpus],
                         [("NVIDIA GeForce GTX 1660", "00000000:01:00.0"), ("NVIDIA GeForce GTX 1060 6GB", "00000000:02:00.0")])

    def test_narrow_slot_note_names_widths_without_blaming_the_card(self):
        # The 1060 sits in Noodlecart's x4 slot; the 1660 runs at its full x16.
        note = [n for n in self.gpus[1]["notes"] if "PCIe link" in n]
        self.assertEqual(len(note), 1)
        self.assertIn("x4", note[0])
        self.assertIn("x16", note[0])
        self.assertIn("doesn't point to a fault in the card", note[0])
        self.assertFalse(any("PCIe link" in n for n in self.gpus[0]["notes"]))

    def test_no_choice_with_two_cards_is_refused_and_lists_them(self):
        g, why = select_gpu(self.report, None)
        self.assertIsNone(g)
        self.assertIn("--gpu", why)
        self.assertIn("02:00.0", why)

    def test_index_and_bus_id_forms_pick_the_same_card(self):
        for wanted in ("1", "02:00.0", "0000:02:00.0", "00000000:02:00.0"):
            g, why = select_gpu(self.report, wanted)
            self.assertIsNone(why, wanted)
            self.assertEqual(g["fields"]["name"]["value"], "NVIDIA GeForce GTX 1060 6GB", wanted)

    def test_unknown_or_malformed_choice_is_refused(self):
        for wanted in ("2", "03:00.0", "gtx1060"):
            g, why = select_gpu(self.report, wanted)
            self.assertIsNone(g, wanted)
            self.assertIn("Found:", why)

    def test_memtest_label_follows_assumed_bus_order(self):
        # Assumed order from memtest_vulkan's main-branch source: highest bus first. Unverified on v0.5.0,
        # which is why the run also checks the tested device.
        self.assertEqual(memtest_label_for(self.gpus, self.gpus[1]), 1)
        self.assertEqual(memtest_label_for(self.gpus, self.gpus[0]), 2)
        self.assertEqual(MemtestVulkan("memtest_vulkan", 1).command(), ["memtest_vulkan", "1"])
        self.assertEqual(MemtestVulkan("memtest_vulkan").command(), ["memtest_vulkan"])


class RealTestedDevice(unittest.TestCase):
    """The tested-device line from real memtest_vulkan runs, against the real Mint two-card capture."""

    def setUp(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660_gtx1060_driver58017804_mint"))
        self.gtx1660, self.gtx1060 = report["gpus"]

    def device_from(self, name):
        return ADAPTER.parse((CAPTURES / name / "stdout.txt").read_text(encoding="utf-8"))["tested_device"]

    def test_tested_device_is_parsed(self):
        self.assertEqual(self.device_from("memtest_gtx1060_full"), {"label": 1, "bus": 1, "device": 0, "dev_id": 0x1C03})

    def test_matching_card_passes_the_check(self):
        # The 1660 was on bus 01 in both the memtest run and the Mint capture.
        self.assertIsNone(device_check(self.device_from("memtest_gtx1660_full"), self.gtx1660, 2))

    def test_other_card_is_caught(self):
        # memtest_vulkan's 1660 run, compared with the Mint 1060: different card, so the result can't apply.
        finding = device_check(self.device_from("memtest_gtx1660_full"), self.gtx1060, 2)
        self.assertEqual((finding["rule"], finding["state"]), ("RUN-008", "INCONCLUSIVE"))

    def test_same_card_in_another_slot_is_caught(self):
        # The 1060 was on bus 01 when tested alone on 2026-11-06, and is on bus 02 now.
        finding = device_check(self.device_from("memtest_gtx1060_full"), self.gtx1060, 2)
        self.assertEqual(finding["rule"], "RUN-008")

    def test_unnamed_device_with_two_cards_cannot_pass(self):
        self.assertEqual(device_check(None, self.gtx1060, 2)["rule"], "RUN-009")
        self.assertIsNone(device_check(None, self.gtx1060, 1))

    def test_wrong_device_finding_makes_run_inconclusive(self):
        tool, samples = load("memtest_gtx1660_full")
        r = evaluate(ev(tool, samples, extra=[device_check(tool["tested_device"], self.gtx1060, 2)]))
        self.assertEqual(r["state"], "INCONCLUSIVE")


def load_mint(card):
    folder = CAPTURES / f"memtest_{card}_mint_driver58017804"
    tool = ADAPTER.parse((folder / "tool_stdout.txt").read_text(encoding="utf-8"))
    samples = [json.loads(line) for line in (folder / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()]
    return tool, samples


class RealMintRuns(unittest.TestCase):
    """Real gpudoc test runs on Mint, both cards installed, driver 580.178.04, 2026-11-08."""

    def setUp(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660_gtx1060_driver58017804_mint"))
        self.gtx1660, self.gtx1060 = report["gpus"]

    def test_each_run_tested_the_selected_card(self):
        # With a device number given, memtest_vulkan printed no header or device list, only this line onward.
        t1060, _ = load_mint("gtx1060")
        t1660, _ = load_mint("gtx1660")
        self.assertEqual(t1060["tested_device"], {"label": 1, "bus": 2, "device": 0, "dev_id": 0x1C03})
        self.assertEqual(t1660["tested_device"], {"label": 2, "bus": 1, "device": 0, "dev_id": 0x2184})
        self.assertIsNone(device_check(t1060["tested_device"], self.gtx1060, 2))
        self.assertIsNone(device_check(t1660["tested_device"], self.gtx1660, 2))
        self.assertTrue(t1060["completed"] and t1660["completed"])

    def test_1060_run_passes_with_thermal_and_power_notes(self):
        tool, samples = load_mint("gtx1060")
        r = evaluate(ev(tool, samples, target_temp=83.0))
        self.assertEqual(r["state"], "PASS")
        notes = {f["rule"]: f for f in r["findings"]}
        self.assertIn("12 of 65", notes["THM-003"]["text"])
        self.assertIn("14 of 65", notes["PWR-001"]["text"])
        self.assertEqual(notes["PWR-001"]["state"], "NOTE")

    def test_1660_run_passes_with_no_slowdown_notes(self):
        tool, samples = load_mint("gtx1660")
        r = evaluate(ev(tool, samples, target_temp=83.0))
        self.assertEqual(r["state"], "PASS")
        self.assertFalse({"THM-002", "THM-003", "PWR-001"} & {f["rule"] for f in r["findings"]})
        self.assertEqual(r["summary"]["peak_temp"], 63)


class KernelLog(unittest.TestCase):
    # A real driver line from Mint's kernel journal, 2026-11-08, with the hostname scrubbed. No real Xid line
    # has been captured yet, so matching an actual Xid event is unverified.
    REAL_NVRM = "2026-11-08T22:08:48+00:00 SCRUBBED-HOST kernel: NVRM: loading NVIDIA UNIX x86_64 Kernel Module  580.178.04  Tue Jul  7 12:38:21 UTC 2026"

    def test_normal_driver_lines_are_not_errors(self):
        r = parse_xid(self.REAL_NVRM, parse_bus_id("00000000:01:00.0"))
        self.assertEqual((r["count"], r["codes"], r["other_cards"]), (0, [], 0))

    def test_empty_log_reads_as_zero(self):
        # journalctl -k returned no lines for the hour before a run on Mint.
        self.assertEqual(parse_xid("", None)["count"], 0)

    def test_xid_48_rule_fails_the_run(self):
        # Rule logic only: the evidence is the real 1660 Mint run, with the Xid code supplied to the rule.
        tool, samples = load_mint("gtx1660")
        r = evaluate(ev(tool, samples, driver_errors=1, xid_codes=[48]))
        self.assertEqual(r["state"], "FAIL")
        self.assertTrue(any(f["rule"] == "DRV-004" for f in r["findings"]))


class RealSweepReadings(unittest.TestCase):
    """Sweep maths on real Mint runs: the 1660 at its default 120 W and at the 70 W minimum."""

    def setUp(self):
        from gpudoc import sweep
        self.sweep = sweep

    def read(self, folder):
        f = CAPTURES / folder
        return ((f / "tool_stdout.txt").read_text(encoding="utf-8"),
                [json.loads(x) for x in (f / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()])

    def test_last_full_window_skips_warm_up_lines(self):
        out, _ = self.read("memtest_gtx1660_mint_70W_60s")
        self.assertEqual(self.sweep.last_full_window(out), {"window_seconds": 30.0246, "write_gbps": 156.8, "check_gbps": 141.7})
        # A run cut off before its first 30-second report gives no reading.
        self.assertIsNone(self.sweep.last_full_window("\n".join(out.splitlines()[:4])))

    def test_power_capped_step_is_summarised(self):
        out, samples = self.read("memtest_gtx1660_mint_70W_60s")
        s = self.sweep.summarise_step(70, out, samples)
        self.assertEqual(s["power_cap_samples"], 12)
        self.assertLessEqual(s["avg_power_w"], 71)
        self.assertEqual(s["traffic_gbps"], 298.5)
        self.assertGreater(s["gbps_per_watt"], 4)

    def test_default_limit_step_is_less_efficient_on_this_memory_bound_work(self):
        out70, s70 = self.read("memtest_gtx1660_mint_70W_60s")
        out120, s120 = self.read("memtest_gtx1660_mint_driver58017804")
        a, b = self.sweep.summarise_step(70, out70, s70), self.sweep.summarise_step(120, out120, s120)
        self.assertGreater(a["gbps_per_watt"], b["gbps_per_watt"])


class BusIdParsing(unittest.TestCase):
    def test_forms_from_nvidia_smi_and_lspci(self):
        # 00000000:02:00.0 is nvidia-smi's form; 02:00.0 is lspci's. Both read from Noodlecart.
        self.assertEqual(parse_bus_id("00000000:02:00.0"), (0, 2, 0, 0))
        self.assertEqual(parse_bus_id("02:00.0"), (0, 2, 0, 0))
        self.assertIsNone(parse_bus_id("02:00"))
        self.assertIsNone(parse_bus_id(None))



class Replay:
    """Answers one command with real saved output, the way CaptureRunner does for inspect."""

    def __init__(self, stdout):
        self.stdout_text = stdout

    def run(self, args):
        from gpudoc.inspect_core import Result
        return Result(0, self.stdout_text, "")


def smi_rows(name):
    """Real nvidia-smi readings of both cards, taken every 5 s during a llama-bench run on one of them."""
    out = []
    for line in (CAPTURES / "llama_bench_two_cards_mint" / name).read_text(encoding="utf-8").splitlines():
        c = [x.strip() for x in line.split(",")]
        out.append((parse_bus_id(c[2]), float(c[6].split()[0])))
    return out


def usage_from(name):
    rows = smi_rows(name)
    usage = {"baseline": dict(rows[:2]), "peak": dict(rows[:2]), "failed": False}
    for i in range(2, len(rows) - 1, 2):
        track_load(usage, dict(rows[i:i + 2]))
    return usage


class RealGpuBurn(unittest.TestCase):
    """gpu-burn commit 0d19c94 on the GTX 1660 Ti, Mint, 2026-11-10: a real 30-second run and its device list."""

    FOLDER = CAPTURES / "gpu_burn_gtx1660ti_mint_30s"

    def text(self):
        return (self.FOLDER / "stdout.txt").read_bytes().decode("utf-8")

    def test_real_clean_run_parses_as_complete(self):
        r = GpuBurn("gpu_burn", 30).parse(self.text())
        self.assertTrue(r["completed"])
        self.assertTrue(r["started"])
        self.assertEqual(r["failure_lines"], [])
        self.assertEqual((r["gflops"], r["iterations"]), (4475, 128))

    def test_progress_alone_is_not_a_pass(self):
        # The same real output, cut where the burn ends and before gpu-burn prints its verdict.
        partial = self.text().split("Killing processes")[0]
        r = GpuBurn("gpu_burn", 30).parse(partial)
        self.assertFalse(r["completed"])
        self.assertGreater(r["gflops"], 0)

    def test_empty_output_is_not_complete(self):
        self.assertFalse(GpuBurn("gpu_burn").parse("")["completed"])

    def test_real_device_list_parses(self):
        listed = GpuBurn.parse_list((self.FOLDER / "list.txt").read_text(encoding="utf-8"))
        self.assertEqual(listed, {0: "NVIDIA GeForce GTX 1660 Ti", 1: "NVIDIA GeForce GTX 1060 6GB"})

    def test_command_names_the_device_and_duration(self):
        self.assertEqual(GpuBurn("gpu_burn", 300, device=1).command()[1:], ["-i", "1", "300"])
        self.assertEqual(GpuBurn("gpu_burn", 300).command()[1:], ["300"])


class RealGpuBurnErrors(unittest.TestCase):
    """A real failing gpu-burn run: the GTX 1660 Ti at +225 MHz during `gpudoc tune` on Mint, 2026-11-11, which
    produced wrong results within seconds. The first real failing output, so CMP-001 is no longer unverified."""

    def test_wrong_results_fail_the_run(self):
        tool = GpuBurn("gpu_burn").parse((CAPTURES / "gpu_burn_gtx1660ti_mint_plus225_errors" / "stdout.txt").read_bytes().decode("utf-8"))
        self.assertFalse(tool["completed"])
        self.assertTrue(tool["failure_lines"])
        self.assertIn("errors: ", tool["failure_lines"][0])
        r = evaluate(ev(tool, [{"temperature_gpu": 57, "memory_used": 5000}]))
        self.assertEqual(r["state"], "FAIL")
        self.assertIn("CMP-001", [f["rule"] for f in r["findings"]])


class RealGpuBurnThroughGpudoc(unittest.TestCase):
    """A real 300-second `gpudoc test --gpu-burn` run on the GTX 1060, Mint, 2026-11-10, with the 1660 Ti also installed."""

    def setUp(self):
        folder = CAPTURES / "gpu_burn_gtx1060_mint_300s"
        self.tool = GpuBurn("gpu_burn").parse((folder / "tool_stdout.txt").read_bytes().decode("utf-8"))
        self.samples = [json.loads(line) for line in (folder / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_run_passes_with_power_and_thermal_notes(self):
        r = evaluate(ev(self.tool, self.samples, total=6144.0, target_temp=83.0))
        self.assertEqual(r["state"], "PASS")
        rules = [f["rule"] for f in r["findings"]]
        self.assertIn("PWR-001", rules)
        self.assertIn("THM-003", rules)
        self.assertEqual(r["summary"]["peak_temp"], 82)
        self.assertEqual(r["summary"]["gflops"], 2999)

    def test_compute_run_gets_no_memory_coverage_note(self):
        r = evaluate(ev(self.tool, self.samples))
        self.assertNotIn("MEM-002", [f["rule"] for f in r["findings"]])
        self.assertNotIn("memory_coverage_percent", r["summary"])


class RealPinnedClock(unittest.TestCase):
    """Two real llama-bench runs on the GTX 1660 Ti, Mint, 2026-11-11: one with the desktop locked, when the card
    ran capped at 1200 MHz with no reason reported, and one three minutes after it was unlocked."""

    def run_of(self, name):
        folder = CAPTURES / name
        tool = LlamaBench("x", "y").parse((folder / "tool_stdout.txt").read_text(encoding="utf-8"))
        samples = [json.loads(line) for line in (folder / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()]
        return evaluate(ev(tool, samples))

    def test_locked_desktop_run_is_flagged_but_still_passes(self):
        r = self.run_of("llama_bench_gtx1660ti_mint_desktop_locked")
        self.assertEqual(r["state"], "PASS")
        self.assertIn("CLK-001", [f["rule"] for f in r["findings"]])
        self.assertEqual(r["summary"]["pinned_gpu_clock_mhz"], 1200)
        self.assertLess(r["summary"]["generation_tokens_per_second"], 31)

    def test_unlocked_run_is_not_flagged(self):
        r = self.run_of("llama_bench_gtx1660ti_mint_desktop_unlocked")
        self.assertNotIn("CLK-001", [f["rule"] for f in r["findings"]])
        self.assertGreater(r["summary"]["generation_tokens_per_second"], 41)

    def test_gpu_burn_run_from_before_clocks_were_recorded_is_not_flagged(self):
        folder = CAPTURES / "gpu_burn_gtx1060_mint_300s"
        samples = [json.loads(line) for line in (folder / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()]
        r = evaluate(ev(GpuBurn("gpu_burn").parse((folder / "tool_stdout.txt").read_bytes().decode("utf-8")), samples))
        self.assertNotIn("CLK-001", [f["rule"] for f in r["findings"]])


class RealTune(unittest.TestCase):
    """Real `gpudoc tune` runs on the GTX 1660 Ti, 2026-11-11: Mint with gpu-burn (every step to +150 MHz passed), and
    Windows with memtest_vulkan (Windows Update replaced the driver during the +75 MHz step). Step results are
    trimmed copies of the real test.json files, without the inspect data that holds identifiers."""

    FOLDER = CAPTURES / "tune_gtx1660ti"

    def load(self, name):
        return json.loads((self.FOLDER / name).read_text(encoding="utf-8"))

    def test_offsets_stay_within_ceiling_and_driver_range(self):
        from gpudoc.tune import plan_offsets
        driver_max = self.load("mint_gpu_burn_tune.json")["clocks_before"]["gpu_offset_max_mhz"]
        self.assertEqual(plan_offsets(25, 150, driver_max), [25, 50, 75, 100, 125, 150])
        self.assertEqual(plan_offsets(25, 150, 60), [25, 50])
        self.assertEqual(plan_offsets(0, 150, driver_max), [])

    def test_real_passing_steps_count_as_stable(self):
        from gpudoc.tune import step_ok
        self.assertEqual(step_ok("gpu_burn", self.load("mint_gpu_burn_plus150_result.json")), (True, ""))
        # memtest_vulkan steps are cut off by time on purpose, so their INCONCLUSIVE for not finishing is expected.
        self.assertEqual(step_ok("memtest_vulkan", self.load("windows_memtest_plus50_result.json")), (True, ""))

    def test_real_crashed_step_is_not_stable(self):
        from gpudoc.tune import step_ok
        ok, problem = step_ok("memtest_vulkan", self.load("windows_memtest_plus75_driver_swapped_result.json"))
        self.assertFalse(ok)
        self.assertIn("ERROR_DEVICE_LOST", problem)

    def test_non_stock_steps_are_stamped(self):
        step = self.load("mint_gpu_burn_plus150_result.json")
        self.assertIs(step["stock_settings"], False)
        self.assertEqual(step["clock_offsets"]["gpu_offset_mhz"], 150)
        self.assertIn("SET-001", [f["rule"] for f in step["findings"]])

    def test_mint_report_names_the_confirmed_setting_and_the_untested_limit(self):
        from gpudoc.tune import to_text
        result = self.load("mint_gpu_burn_tune.json")
        text = to_text(result)
        self.assertEqual(result["fastest_stable"]["gpu_clock_offset_mhz"], 150)
        self.assertIn("Fastest stable setting found: +150 MHz", text)
        self.assertIn("real limit wasn't found", text)
        self.assertIn("returned to stock clocks: yes", text)

    def test_windows_report_confirms_nothing_and_flags_the_failed_restore(self):
        from gpudoc.tune import to_text
        result = self.load("windows_memtest_tune.json")
        text = to_text(result)
        self.assertIsNone(result["fastest_stable"])
        self.assertIn("No offset above stock was confirmed stable.", text)
        self.assertIn("First problem at +75 MHz", text)
        self.assertIn("NO, run gpudoc tune --reset", text)


class RealDcgm(unittest.TestCase):
    """Real `dcgmi` output from DCGM 4.8.0 on Mint, 2026-11-12, GTX 1660 Ti (bus 01) and GTX 1060 (bus 02)."""

    FOLDER = CAPTURES / "dcgm_gtx1660ti_gtx1060_mint"

    def parse(self, name, entity=None, dev=None):
        a = DcgmDiag()
        a.entity, a.expect_dev = entity, dev
        return a, a.parse((self.FOLDER / name).read_text(encoding="utf-8"))

    def test_discovery_maps_bus_ids_to_dcgm_ids(self):
        ids = DcgmDiag.parse_discovery((self.FOLDER / "discovery.txt").read_text(encoding="utf-8"))
        self.assertEqual(ids, {parse_bus_id("01:00.0"): 0, parse_bus_id("02:00.0"): 1})

    def test_passing_level_1_run_passes(self):
        a, tool = self.parse("pm_diag_r1_gpu0.json", 0, "2182")
        self.assertTrue(tool["completed"])
        self.assertEqual(tool["tests"], [{"category": "Deployment", "name": "software", "status": "Pass"}])
        self.assertIsNone(a.verify(tool))
        self.assertEqual(evaluate(ev(tool, [{"temperature_gpu": 40, "memory_used": 300}]))["state"], "PASS")

    def test_persistence_mode_failure_needs_attention_not_a_fail(self):
        # The real run before persistence mode was turned on.
        _, tool = self.parse("diag_r1_gpu1.json", 1, "1c03")
        r = evaluate(ev(tool, [{"temperature_gpu": 40, "memory_used": 300}]))
        self.assertEqual(r["state"], "ATTENTION")
        self.assertIn("Persistence Mode", next(f["text"] for f in r["findings"] if f["rule"] == "DCG-001"))

    def test_missing_plugin_error_is_inconclusive(self):
        # The real Ti run before DCGM's CUDA 13 plugins were installed.
        _, tool = self.parse("diag_r1_gpu0.json", 0, "2182")
        self.assertFalse(tool["completed"])
        r = evaluate(ev(tool, [{"temperature_gpu": 40, "memory_used": 300}]))
        self.assertEqual(r["state"], "INCONCLUSIVE")
        self.assertIn("RUN-016", [f["rule"] for f in r["findings"]])

    def test_level_2_skips_are_noted_on_geforce(self):
        _, tool = self.parse("pm_diag_r2_gpu1.json", 1, "1c03")
        r = evaluate(ev(tool, [{"temperature_gpu": 40, "memory_used": 300}]))
        self.assertEqual(r["state"], "PASS")
        self.assertEqual([f["rule"] for f in r["findings"]].count("DCG-002"), 2)

    def test_other_card_is_caught(self):
        a, tool = self.parse("pm_diag_r1_gpu1.json", 0, "2182")
        self.assertEqual(a.verify(tool)["rule"], "RUN-008")


class RealGpuFryer(unittest.TestCase):
    """Real gpu-fryer 1.0.0 output, 30 s on each card, Mint, 2026-11-12, run with CUDA_VISIBLE_DEVICES set to one card.
    The UUIDs in the captures are replaced with placeholder values."""

    FOLDER = CAPTURES / "gpu_fryer_mint_30s"

    def tool(self, g):
        return GpuFryer("gpu-fryer").parse((self.FOLDER / f"gpu{g}_stdout.txt").read_text(encoding="utf-8"))

    def test_real_runs_parse_as_complete(self):
        ti, gtx1060 = self.tool(0), self.tool(1)
        self.assertTrue(ti["completed"] and gtx1060["completed"])
        self.assertEqual((ti["gflops"], gtx1060["gflops"]), (5014, 3474))
        self.assertEqual(ti["attention_lines"], [])
        self.assertEqual(ti["detected"][0]["name"], "NVIDIA GeForce GTX 1660 Ti")

    def test_summary_without_the_healthy_line_is_not_a_pass(self):
        text = (self.FOLDER / "gpu0_stdout.txt").read_text(encoding="utf-8").replace("All GPUs seem healthy", "")
        tool = GpuFryer("gpu-fryer").parse(text)
        self.assertFalse(tool["completed"])
        self.assertIn("CMP-002", [f["rule"] for f in evaluate(ev(tool, [{"temperature_gpu": 50, "memory_used": 5000}]))["findings"]])

    def test_detected_card_is_checked(self):
        a = GpuFryer("gpu-fryer")
        a.expect_uuid = "00000000-0000-0000-0000-000000000000"
        self.assertIsNone(a.verify(self.tool(0)))
        self.assertEqual(a.verify(self.tool(1))["rule"], "RUN-008")

    def test_selection_limits_it_to_one_card(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660ti_gtx1060_driver58017804_mint"))
        a = GpuFryer("gpu-fryer")
        if not sys.platform.startswith("linux"):
            self.assertIn("Linux", a.prepare(report["gpus"], report["gpus"][1], None))
            return
        self.assertIsNone(a.prepare(report["gpus"], report["gpus"][1], None))
        self.assertEqual(a.env, {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUDA_VISIBLE_DEVICES": "1"})


class RealLocalScore(unittest.TestCase):
    """Real LocalScore 0.9.3 runs on Mint, 2026-11-12, one per card, network blocked, with -n."""

    FOLDER = CAPTURES / "localscore_mint"

    def tool(self, g):
        return LocalScore("localscore", "m.gguf", block_network=False).parse((self.FOLDER / f"run_gpu{g}.stdout").read_text(encoding="utf-8"))

    def test_real_runs_parse_and_confirm_nothing_was_sent(self):
        ti, gtx1060 = self.tool(0), self.tool(1)
        self.assertTrue(ti["completed"] and gtx1060["completed"])
        self.assertEqual((ti["generation_tokens_per_second"], gtx1060["generation_tokens_per_second"]), (37.06, 71.78))
        self.assertEqual(len(ti["localscore_tests"]), 9)
        self.assertEqual(ti["attention_lines"], [])

    def test_missing_not_submitted_line_needs_attention(self):
        text = (self.FOLDER / "run_gpu0.stdout").read_text(encoding="utf-8").replace("Results Not Submitted.", "")
        tool = LocalScore("localscore", "m.gguf", block_network=False).parse(text)
        self.assertFalse(tool["completed"])
        self.assertIn("can't be confirmed", tool["attention_lines"][0])

    def test_card_is_picked_by_name_and_checked(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660ti_gtx1060_driver58017804_mint"))
        a = LocalScore("localscore", "m.gguf", block_network=False)
        self.assertIsNone(a.prepare(report["gpus"], report["gpus"][1], Replay((self.FOLDER / "list_gpus.txt").read_text(encoding="utf-8"))))
        self.assertEqual(a.index, 1)
        self.assertEqual(a.command()[-6:], ["-g", "nvidia", "-i", "1", "-n", "-o", "json"][-6:])
        self.assertNotIn("-y", a.command())
        self.assertIsNone(a.verify(self.tool(1)))
        self.assertEqual(a.verify(self.tool(0))["rule"], "RUN-008")

    def test_gtx16_card_gets_a_note(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660ti_gtx1060_driver58017804_mint"))
        listing = Replay((self.FOLDER / "list_gpus.txt").read_text(encoding="utf-8"))
        ti, gtx1060 = (LocalScore("localscore", "m.gguf", block_network=False) for _ in range(2))
        ti.prepare(report["gpus"], report["gpus"][0], listing)
        gtx1060.prepare(report["gpus"], report["gpus"][1], listing)
        text = (self.FOLDER / "run_gpu0.stdout").read_text(encoding="utf-8")
        r = evaluate(ev(ti.parse(text), [{"temperature_gpu": 60, "memory_used": 1500}]))
        self.assertEqual(r["state"], "PASS")
        self.assertIn("LLM-001", [f["rule"] for f in r["findings"]])
        self.assertNotIn("note_lines", gtx1060.parse((self.FOLDER / "run_gpu1.stdout").read_text(encoding="utf-8")))

    def test_linux_runs_have_no_network(self):
        a = LocalScore("localscore", "m.gguf", block_network=True)
        self.assertEqual(a.command()[:4], ["sudo", "-n", "unshare", "-n"])


class RealWattever(unittest.TestCase):
    """A real Wattever 2.6.1 run through GPUDoc's driver on the GTX 1660 Ti, Mint, 2026-11-12, trimmed to the fields read."""

    FOLDER = CAPTURES / "wattever_gtx1660ti_mint"

    def test_real_run_parses(self):
        tmp = Path(tempfile.mkdtemp())
        run = tmp / "run.json"
        run.write_text((self.FOLDER / "run_trimmed.json").read_text(encoding="utf-8"), encoding="utf-8")
        text = (self.FOLDER / "driver_tail.txt").read_text(encoding="utf-8").replace("RUN_FILE", str(run).replace("\\", "/"))
        tool = Wattever("w", "s", "m").parse(text)
        self.assertTrue(tool["completed"])
        self.assertEqual((tool["results"], tool["ok"]), (4, 4))
        self.assertEqual([x["prompt_tokens"] for x in tool["wattever_sizes"]], [512, 4000])
        self.assertAlmostEqual(tool["generation_tokens_per_second"], 41.17, places=1)

    def test_missing_result_line_is_not_complete(self):
        self.assertFalse(Wattever("w", "s", "m").parse("llama-server ready")["completed"])


class RealLlamaDeviceSelection(unittest.TestCase):
    """llama-bench b12177 on Mint with the GTX 1660 Ti (bus 01) and GTX 1060 (bus 02), 2026-11-10."""

    FOLDER = CAPTURES / "llama_bench_two_cards_mint"

    def setUp(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660ti_gtx1060_driver58017804_mint"))
        self.gpus = report["gpus"]
        self.ti, self.gtx1060 = self.gpus
        self.listing = (self.FOLDER / "list_devices.txt").read_text(encoding="utf-8")

    def test_real_device_list_parses(self):
        self.assertEqual(LlamaBench.parse_devices(self.listing),
                         [("Vulkan0", "NVIDIA GeForce GTX 1660 Ti"), ("Vulkan1", "NVIDIA GeForce GTX 1060 6GB")])

    def test_selected_card_gets_its_device(self):
        a = LlamaBench("llama-bench", "model.gguf")
        self.assertIsNone(a.prepare(self.gpus, self.gtx1060, Replay(self.listing)))
        self.assertEqual(a.device, "Vulkan1")
        self.assertEqual(a.command()[3:5], ["-dev", "Vulkan1"])

    def test_one_card_needs_no_device(self):
        a = LlamaBench("llama-bench", "model.gguf")
        self.assertIsNone(a.prepare([self.ti], self.ti, Replay("")))
        self.assertNotIn("-dev", a.command())

    def test_card_missing_from_the_list_is_refused(self):
        # The real list from the Ti and 1060 layout, against the regular 1660 from the earlier layout.
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660_gtx1060_driver58017804_mint"))
        why = LlamaBench("llama-bench", "model.gguf").prepare(report["gpus"], report["gpus"][0], Replay(self.listing))
        self.assertIn("didn't run", why)

    def test_reported_device_is_checked(self):
        text = (self.FOLDER / "vulkan0.jsonl").read_text(encoding="utf-8")
        right, wrong = LlamaBench("x", "y", device="Vulkan0"), LlamaBench("x", "y", device="Vulkan1")
        tool = right.parse(text)
        self.assertTrue(tool["completed"])
        self.assertEqual(tool["devices"], "Vulkan0")
        self.assertIsNone(right.verify(tool))
        self.assertEqual(wrong.verify(tool)["rule"], "RUN-008")

    def test_load_on_the_selected_card_only_is_accepted(self):
        self.assertEqual(load_findings(usage_from("smi_vulkan0.csv"), parse_bus_id("01:00.0")), [])
        self.assertEqual(load_findings(usage_from("smi_vulkan1.csv"), parse_bus_id("02:00.0")), [])

    def test_load_on_the_other_card_is_caught(self):
        # The real run on the Ti, judged as if the 1060 had been selected.
        usage = usage_from("smi_vulkan0.csv")
        self.assertEqual(strayed(usage, parse_bus_id("02:00.0")), [parse_bus_id("01:00.0")])
        self.assertEqual([f["rule"] for f in load_findings(usage, parse_bus_id("02:00.0"))], ["RUN-014", "RUN-015"])

    def test_unreadable_memory_cannot_confirm_the_card(self):
        usage = usage_from("smi_vulkan0.csv")
        track_load(usage, None)
        self.assertEqual([f["rule"] for f in load_findings(usage, parse_bus_id("01:00.0"))], ["RUN-009"])



class WebPage(unittest.TestCase):
    """The local web page's request handling. No test is ever started here: every request below is one the page refuses
    or one that only reads. Run listing uses trimmed real suite.json files from the clean all-adapter run, 2026-11-12."""

    @classmethod
    def setUpClass(cls):
        import threading
        from gpudoc.web import make_server
        cls.tmp = Path(tempfile.mkdtemp())
        tools = cls.tmp / "tools.json"
        tools.write_text(json.dumps({"gpu_burn": "/opt/gpu_burn", "llama_bench": "/opt/llama-bench", "model": "/m/q.gguf",
                                     "wattever": "/opt/wattever", "llama_server": "/opt/llama-server"}), encoding="utf-8")
        cls.httpd = make_server(0, tools, CAPTURES / "web_runs")
        cls.port = cls.httpd.server_port
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, method, path, body=None, headers=None):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        c.request(method, path, body=json.dumps(body) if isinstance(body, dict) else body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_tool_arguments(self):
        from gpudoc.web import test_args
        cfg = {"gpu_burn": "/b", "llama_bench": "/lb", "model": "/m", "wattever": "/w", "llama_server": "/ls"}
        args = test_args(cfg, ["gpu_burn", "llama_bench", "wattever"], "01:00.0", Path("out"))
        self.assertEqual(args[:9], ["test", "--gpu", "01:00.0", "--out", "out", "--max-seconds", "900", "--yes", "--gpu-burn"])
        self.assertEqual(args.count("--model"), 1)
        for bad in (["nope"], ["localscore"], []):
            with self.assertRaises(ValueError):
                test_args(cfg, bad, "01:00.0", Path("out"))

    def test_paths_cannot_leave_the_results_folder(self):
        from gpudoc.web import safe_child
        base = CAPTURES / "web_runs"
        self.assertIsNone(safe_child(base, "../../src/gpudoc/web.py"))
        self.assertIsNotNone(safe_child(base, "test-20261112-045134/gpu0_00000000-01-00.0/suite.json"))
        self.assertEqual(self.request("GET", "/runs/..%2F..%2Ftest_testing.py")[0], 404)

    def test_real_runs_are_listed(self):
        code, data = self.request("GET", "/api/runs")
        runs = json.loads(data)["runs"]
        self.assertEqual(code, 200)
        self.assertEqual([c["state"] for c in runs[0]["cards"]], ["PASS", "PASS"])
        self.assertEqual([s["tool"] for s in runs[0]["cards"][0]["steps"]],
                         ["dcgm_diag", "gpu_burn", "gpu_fryer", "llama_bench", "localscore", "wattever"])

    def test_only_configured_tools_are_offered(self):
        tools = {t["id"]: t["available"] for t in json.loads(self.request("GET", "/api/info")[1])["tools"]}
        self.assertTrue(tools["gpu_burn"] and tools["wattever"])
        self.assertFalse(tools["localscore"] or tools["memtest"])

    def test_other_hosts_and_origins_are_refused(self):
        self.assertEqual(self.request("GET", "/api/info", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/stop", {}, {"Origin": "http://attacker.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/run", "confirm=YES", {"Content-Type": "text/plain"})[0], 415)

    def test_a_run_needs_confirmation_a_card_and_a_tool(self):
        self.assertEqual(self.request("POST", "/api/run", {"gpu": "01:00.0", "tools": ["gpu_burn"]})[0], 400)
        self.assertEqual(self.request("POST", "/api/run", {"tools": ["gpu_burn"], "confirm": "YES"})[0], 400)
        self.assertEqual(self.request("POST", "/api/run", {"gpu": "01:00.0", "tools": [], "confirm": "YES"})[0], 400)
        self.assertFalse(self.httpd.app["runner"].running())

    @unittest.skipUnless(sys.platform.startswith("linux"), "the die-with-parent signal is Linux only")
    def test_started_process_outlives_the_request_thread(self):
        # The real bug from 2026-11-13: a process started from a short-lived request thread was killed when the thread
        # ended. This starts a harmless real process (sleep) the same way and checks it is still running afterwards.
        import threading
        from gpudoc.web import Runner
        out = Path(tempfile.mkdtemp())
        r = Runner(out)
        holder = {}
        t = threading.Thread(target=lambda: holder.update(r=r.start(["--version"])))
        orig = sys.executable
        try:
            sys.executable = "/bin/sleep"
            # "-c <code>" is prepended by Runner; sleep would reject it, so point the code argument at a duration instead.
            import gpudoc.web as web
            real_popen = web.subprocess.Popen
            web.subprocess.Popen = lambda cmd, **kw: real_popen(["/bin/sleep", "3"], **kw)
            t.start()
            t.join()
            time.sleep(1)
            self.assertTrue(r.running(), holder)
        finally:
            sys.executable = orig
            web.subprocess.Popen = real_popen
            if r.proc:
                r.proc.wait(timeout=10)

    def test_stop_with_nothing_running_is_refused(self):
        self.assertEqual(self.request("POST", "/api/stop", {})[0], 409)


if __name__ == "__main__":
    unittest.main()
