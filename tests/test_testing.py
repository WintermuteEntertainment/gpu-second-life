"""Rules and parsers are tested with real memtest_vulkan logs and telemetry from Noodlecart."""
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from gpudoc.inspect_core import CaptureRunner, inspect, parse_valid_fields
from gpudoc.testing import (Evidence, LlamaBench, MemtestVulkan, combine, device_check, energy_wh, evaluate, memtest_label_for,
                            parse_bus_id, resolve_sample_fields, select_gpu, stop_and_confirm, temp_limit_for, wait_until_idle)

CAPTURES = Path(__file__).parent / "captures"
ADAPTER = MemtestVulkan("memtest_vulkan")


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

    def test_1060_full_run_gets_thermal_attention(self):
        tool, samples = load("memtest_gtx1060_full")
        r = evaluate(ev(tool, samples))
        self.assertEqual(r["state"], "ATTENTION")
        self.assertTrue(any(f["rule"] == "THM-002" for f in r["findings"]))

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
            r = subprocess.run(["tasklist", "/FI", f"PID eq {child}", "/NH"], capture_output=True, text=True)
            self.assertNotIn(child, r.stdout)

    def test_already_exited_process_is_reported(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        self.assertEqual(stop_and_confirm(p)["method"], "already_exited")


class RealFieldData(unittest.TestCase):
    def test_sample_fields_exist_on_the_real_driver(self):
        text = (CAPTURES / "gtx1660_driver61088_windows" / "help_query_gpu.txt").read_text(encoding="utf-8")
        self.assertEqual(len(resolve_sample_fields(parse_valid_fields(text))), 10)

    def test_temperature_limit_respects_real_slowdown_limit(self):
        self.assertEqual(temp_limit_for({"slowdown_temp": 93.0}, None), 85)
        self.assertEqual(temp_limit_for({"slowdown_temp": 93.0}, 90), 88)


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


class BusIdParsing(unittest.TestCase):
    def test_forms_from_nvidia_smi_and_lspci(self):
        # 00000000:02:00.0 is nvidia-smi's form; 02:00.0 is lspci's. Both read from Noodlecart.
        self.assertEqual(parse_bus_id("00000000:02:00.0"), (0, 2, 0, 0))
        self.assertEqual(parse_bus_id("02:00.0"), (0, 2, 0, 0))
        self.assertIsNone(parse_bus_id("02:00"))
        self.assertIsNone(parse_bus_id(None))


if __name__ == "__main__":
    unittest.main()
