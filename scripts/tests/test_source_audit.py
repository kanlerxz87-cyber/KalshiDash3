#!/usr/bin/env python3
"""Independent citation regression tests; discovered by verify_release.py.

These checks cannot and do not certify the truth of linked market values.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_sources import audit, claim_source, demo_source  # noqa: E402

BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
TICKER = "KXBTCY-27JAN0100-B57500"
URL = f"{BASE}/markets/{TICKER}"


def fixture():
    return {
        "markets": {"environment": "demo", "base_url": BASE,
                    "open_markets": [{"ticker": TICKER, "source": URL}],
                    "settled_markets": [], "liquidity": [], "series_index": {}},
        "alerts": {"all_events": [], "high_roi": []},
        "alerts_archive": {"alerts": []},
        "roi": {"environment": "demo", "base_url": BASE,
                "picks": [], "near_misses": [], "unscoreable": [], "alerts": []},
        "simulation": {"environment": "demo", "endpoint": BASE,
                       "open_positions": [], "settled_positions": []},
        "catalysts": {"alerts": []},
        "facts": {"facts": [{"id": "C-test", "verified": False, "value": "",
                             "flag": "Unverified, left blank.",
                             "source": "https://docs.kalshi.com/api-reference/market/get-markets"}]},
    }


def write_fixture(root, docs):
    (root / "data/live").mkdir(parents=True)
    for name, doc in docs.items():
        path = root / ("data/verified_facts.json" if name == "facts" else f"data/live/{name}.json")
        path.write_text(json.dumps(doc))


class SourceURLTests(unittest.TestCase):
    def test_exact_recommended_and_supported_hosts(self):
        self.assertTrue(demo_source(URL, TICKER))
        self.assertTrue(demo_source(URL.replace("external-api.demo", "demo-api"), TICKER))

    def test_production_is_not_demo(self):
        self.assertFalse(demo_source(URL.replace("external-api.demo.kalshi.co", "external-api.kalshi.com"), TICKER))

    def test_host_spoofing_and_ambiguous_urls_are_refused(self):
        for bad in (
            URL.replace("kalshi.co/", "kalshi.co.evil.example/"),
            URL.replace("https://", "https://evil.example@"),
            URL.replace("https://", "https://user:password@"),
            URL.replace("kalshi.co/", "kalshi.co:443/"),
            URL.replace("kalshi.co/", "kalshi.co./"),
            URL.replace("https://", "http://"),
            URL + "#source", URL + "?redirect=https://evil.example",
            URL + "\n", URL.replace("/markets/", "\\markets/"),
            URL.replace("https://", "https://[invalid/"), "javascript:alert(1)",
            "//external-api.demo.kalshi.co/trade-api/v2/markets/" + TICKER,
            "", None, 12,
        ):
            with self.subTest(url=bad):
                self.assertFalse(demo_source(bad, TICKER))

    def test_ticker_and_route_must_match(self):
        self.assertFalse(demo_source(URL, "OTHER"))
        self.assertFalse(demo_source(URL, "../" + TICKER))
        self.assertFalse(demo_source(URL + "/orderbook", TICKER))
        self.assertFalse(demo_source(URL, TICKER, "series"))
        self.assertFalse(demo_source(URL, TICKER, "typo"))
        self.assertTrue(demo_source(BASE + "/series/KXBTCY", "KXBTCY", "series"))

    def test_orderbook_depth_only(self):
        for suffix in ("", "?depth=10", "?depth=0"):
            self.assertTrue(demo_source(URL + "/orderbook" + suffix, TICKER, "orderbook"))
        for suffix in ("?depth=-1", "?depth=", "?depth=10&depth=20", "?other=10"):
            self.assertFalse(demo_source(URL + "/orderbook" + suffix, TICKER, "orderbook"))

    def test_fact_hosts_are_explicit(self):
        self.assertTrue(claim_source("https://docs.kalshi.com/getting_started/demo_env"))
        self.assertTrue(claim_source("https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/COORDINATION.md"))
        self.assertFalse(claim_source("https://github.com/someone/kalshi-lookalike"))
        self.assertFalse(claim_source("https://docs.kalshi.com.evil.example/docs"))


class AuditTests(unittest.TestCase):
    def run_audit(self, docs):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root, docs)
            return audit(root)

    def test_valid_fixture_and_blank_unverified_value(self):
        result = self.run_audit(fixture())
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["counts"]["unverified_facts"], 1)
        self.assertIn("NOT verification", result["scope"])

    def test_each_public_row_group_is_audited(self):
        for filename, groups, key in (
            ("markets", ("open_markets", "settled_markets"), "source"),
            ("alerts", ("all_events", "high_roi"), "market_source"),
            ("alerts_archive", ("alerts",), "market_source"),
            ("roi", ("picks", "near_misses", "unscoreable", "alerts"), "source"),
            ("simulation", ("open_positions", "settled_positions"), "source"),
            ("catalysts", ("alerts",), "market_source"),
        ):
            for group in groups:
                with self.subTest(file=filename, group=group):
                    docs = fixture()
                    docs[filename][group] = [{"ticker": TICKER, key: URL.replace(TICKER, "WRONG")}]
                    self.assertFalse(self.run_audit(docs)["passed"])

    def test_series_and_orderbook_links(self):
        docs = fixture()
        docs["markets"]["series_index"] = {"KXBTCY": {"source": BASE + "/series/KXBTCY"}}
        docs["markets"]["liquidity"] = [{"ticker": TICKER, "orderbook": {"source": URL + "/orderbook?depth=10"}}]
        self.assertTrue(self.run_audit(docs)["passed"])
        docs["markets"]["liquidity"][0]["orderbook"]["source"] = URL
        self.assertFalse(self.run_audit(docs)["passed"])

    def test_unverified_values_cannot_be_filled(self):
        docs = fixture()
        docs["facts"]["facts"][0]["value"] = "guessed value"
        self.assertFalse(self.run_audit(docs)["passed"])

    def test_missing_flags_and_verification_states_fail(self):
        for field in ("flag", "verified", "source"):
            docs = fixture()
            del docs["facts"]["facts"][0][field]
            self.assertFalse(self.run_audit(docs)["passed"])

    def test_missing_malformed_documents_and_groups_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(audit(Path(tmp))["passed"])
        for bad in (None, {}, "not a list"):
            docs = fixture()
            docs["alerts"]["all_events"] = bad
            self.assertFalse(self.run_audit(docs)["passed"])
        docs = fixture()
        docs["markets"]["open_markets"] = [None]
        self.assertFalse(self.run_audit(docs)["passed"])

    def test_demo_environment_and_root_are_exact(self):
        for name in ("markets", "roi", "simulation"):
            docs = fixture()
            docs[name]["environment"] = "production"
            self.assertFalse(self.run_audit(docs)["passed"])
            docs = fixture()
            docs[name]["endpoint" if name == "simulation" else "base_url"] = "https://fake-demo.example/trade-api/v2"
            self.assertFalse(self.run_audit(docs)["passed"])

    def test_cli_returns_failure_for_missing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, str(ROOT / "scripts/audit_sources.py"),
                                   "--root", tmp, "--json"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(json.loads(proc.stdout)["passed"])

    def test_committed_public_sources(self):
        result = audit(ROOT)
        self.assertTrue(result["passed"], "\n".join(result["errors"]))
        self.assertGreater(result["counts"]["markets.open_markets"], 0)
        self.assertGreater(result["counts"]["facts"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
