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

from gpudoc.testing import (Evidence, LlamaBench, MemtestVulkan, combine, device_check, energy_wh, evaluate, memtest_label_for,
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

    def test_already_exited_process_is_reported(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        self.assertEqual(stop_and_confirm(p)["method"], "already_exited")


class RealFieldData(unittest.TestCase):
    def test_sample_fields_exist_on_the_real_driver(self):
        text = (CAPTURES / "gtx1660_driver61088_windows" / "help_query_gpu.txt").read_text(encoding="utf-8")
        self.assertEqual(len(resolve_sample_fields(parse_valid_fields(text))), 10)

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


if __name__ == "__main__":
    unittest.main()
