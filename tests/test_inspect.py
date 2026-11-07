"""Tests use real captured nvidia-smi output only. See tests/captures/README.md."""
import json
import unittest
from pathlib import Path

from gpudoc.inspect_core import (CaptureRunner, FIELDS, inspect, parse_cell, parse_valid_fields, redact, resolve_fields,
                                 to_markdown)
from gpudoc.report_html import to_html

CAPTURES = Path(__file__).parent / "captures"
G1660 = CAPTURES / "gtx1660_driver61088_windows"


class RealGtx1660(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.raw = inspect(CaptureRunner(G1660))
        cls.gpu = cls.report["gpus"][0]
        cls.f = cls.gpu["fields"]

    def test_complete_single_gpu(self):
        self.assertTrue(self.report["complete"])
        self.assertEqual(self.report["errors"], [])
        self.assertEqual(len(self.report["gpus"]), 1)

    def test_identity(self):
        self.assertEqual(self.f["name"]["value"], "NVIDIA GeForce GTX 1660")
        self.assertEqual(self.f["vbios_version"]["value"], "90.16.34.00.c9")
        self.assertEqual(self.f["memory_total"]["value"], 6144.0)
        self.assertEqual(self.gpu["details"]["architecture"], "Turing")
        self.assertEqual(self.gpu["details"]["slowdown_temp"], 93.0)

    def test_missing_is_never_zero(self):
        for key in ("ecc_mode", "ecc_uncorrected_lifetime", "retired_pages_double_bit", "remapped_rows_failure",
                    "temperature_memory", "serial"):
            self.assertEqual(self.f[key]["status"], "not_available", key)
            self.assertIsNone(self.f[key]["value"], key)

    def test_every_catalog_field_reported(self):
        self.assertEqual(set(self.f), {k for k, *_ in FIELDS})

    def test_ecc_note_asks_for_memory_test(self):
        self.assertTrue(any("memory pattern test" in n for n in self.gpu["notes"]))
        self.assertFalse(any("Lifetime uncorrected ECC count is zero" in n for n in self.gpu["notes"]))

    def test_cross_checks_all_match(self):
        results = {c["field"]: c["result"] for c in self.gpu["crosschecks"]}
        self.assertNotIn("mismatch", results.values())
        self.assertEqual(results["memory_total"], "match")
        self.assertEqual(results["pcie_width_max"], "match")

    def test_real_fields_resolved_from_real_help(self):
        help_text = (G1660 / "help_query_gpu.txt").read_text(encoding="utf-8")
        mapping = resolve_fields(parse_valid_fields(help_text))
        self.assertNotIn(None, mapping.values())

    def test_redaction_removes_identifiers(self):
        safe = redact(self.report)
        self.assertEqual(safe["gpus"][0]["fields"]["uuid"]["status"], "redacted")
        self.assertIsNone(safe["gpus"][0]["fields"]["uuid"]["value"])
        self.assertNotIn("pci_bus_id", safe["gpus"][0]["details"])
        text = json.dumps(safe)
        self.assertNotIn("GPU-SCRUBBED", text)
        self.assertNotIn('"args"', text)
        # Redaction must not change the source report.
        self.assertEqual(self.f["uuid"]["value"], "GPU-SCRUBBED")

    def test_report_is_explicit_about_limits(self):
        self.assertIn("not a health verdict", to_markdown(self.report))


class RealNvmlCrossCheck(unittest.TestCase):
    def test_local_run_matches_nvml(self):
        report, raw = inspect(CaptureRunner(CAPTURES / "gtx1660_driver61088_windows_local"))
        nv = report["gpus"][0]["nvml_crosscheck"]
        self.assertEqual(nv["status"], "run")
        self.assertEqual({c["result"] for c in nv["checks"]}, {"match"})
        self.assertIn("nvml.json", raw)

    def test_wsl_run_matches_nvml(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660_driver61088_wsl2"))
        self.assertTrue(report["complete"])
        nv = report["gpus"][0]["nvml_crosscheck"]
        self.assertEqual({c["result"] for c in nv["checks"]}, {"match"})
        self.assertEqual(report["gpus"][0]["fields"]["ecc_mode"]["status"], "not_available")

    def test_ssh_capture_says_nvml_did_not_run(self):
        report, _ = inspect(CaptureRunner(G1660))
        self.assertEqual(report["gpus"][0]["nvml_crosscheck"]["status"], "not_run")
        self.assertIn("not_run", to_markdown(report))


class RealHtmlReport(unittest.TestCase):
    def test_report_is_self_contained_and_honest(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "gtx1660_driver61088_windows_local"))
        page = to_html(report)
        self.assertIn("NVIDIA GeForce GTX 1660", page)
        self.assertIn("not available", page)
        self.assertIn("not a health verdict", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("http", page)
        self.assertIn('id="t-dark"', page)
        self.assertNotIn("DARK", page)

    def test_every_field_has_label_and_explanation(self):
        from gpudoc.report_html import EXPLAIN, LABELS
        for key, *_ in FIELDS:
            self.assertIn(key, LABELS)
            self.assertIn(key, EXPLAIN)

    def test_redacted_report_hides_identifier(self):
        report, _ = inspect(CaptureRunner(G1660))
        page = to_html(redact(report))
        self.assertNotIn("GPU-SCRUBBED", page)
        self.assertIn("redacted", page)

    def test_missing_evidence_is_visible(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "this-folder-does-not-exist"))
        page = to_html(report)
        self.assertIn("Incomplete", page)
        self.assertIn("No GPU data", page)


class RealTokens(unittest.TestCase):
    def test_placeholders_seen_on_real_cards(self):
        self.assertEqual(parse_cell("[N/A]", "int"), ("not_available", None))
        self.assertEqual(parse_cell("N/A", "int"), ("not_available", None))


class MissingEvidence(unittest.TestCase):
    def test_no_capture_is_incomplete_not_a_pass(self):
        report, _ = inspect(CaptureRunner(CAPTURES / "this-folder-does-not-exist"))
        self.assertFalse(report["complete"])
        self.assertEqual(report["gpus"], [])
        self.assertTrue(report["errors"])
        self.assertIn("NO", to_markdown(report))

    def test_real_csv_with_missing_xml_is_incomplete(self):
        class NoXml(CaptureRunner):
            def run(self, args):
                r = super().run(args)
                if "-x" in args:
                    r.returncode, r.stdout, r.stderr = 1, "", "xml unavailable"
                return r

        report, _ = inspect(NoXml(G1660))
        self.assertFalse(report["complete"])
        self.assertEqual(report["gpus"][0]["crosschecks"][0]["result"], "not_compared")


if __name__ == "__main__":
    unittest.main()
