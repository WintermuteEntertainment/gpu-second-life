"""Rules and parsers are tested with real memtest_vulkan logs and telemetry from Noodlecart."""
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from gpudoc.inspect_core import parse_valid_fields
from gpudoc.testing import (Evidence, LlamaBench, MemtestVulkan, combine, energy_wh, evaluate, resolve_sample_fields,
                            stop_and_confirm, temp_limit_for, wait_until_idle)

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


if __name__ == "__main__":
    unittest.main()
