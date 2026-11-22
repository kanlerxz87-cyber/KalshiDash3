#!/usr/bin/env python3
"""Offline demo-executor safety regression tests. No keys or network required.

Endpoint allowlist: https://docs.kalshi.com/getting_started/demo_env
Signed path: https://docs.kalshi.com/getting_started/api_keys
Order body: https://docs.kalshi.com/api-reference/orders/create-order-v2
Redirect refusal and no silent rounding are project safety policies, not claims
that Kalshi sends redirects or accepts every locally valid order.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from email.message import Message
from html.parser import HTMLParser
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch
import urllib.request
from urllib.response import addinfourl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kalshi_client as client


class FakeHTTPS(urllib.request.HTTPSHandler):
    """Exercise urllib's real redirect/error processing, never a real socket."""

    def __init__(self, status=200, body=b'{"ok": true}', location=None):
        super().__init__()
        self.status, self.body, self.location = status, body, location
        self.requests = []

    def https_open(self, req):
        self.requests.append(req)
        headers = Message()
        if self.location:
            headers["Location"] = self.location
        response = addinfourl(BytesIO(self.body), headers, req.full_url, self.status)
        response.msg = "test fixture"
        return response


class ClientSafety(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_documented_demo_roots_and_one_trailing_slash(self):
        self.assertEqual(client.base_url(), client.DEFAULT_BASE)
        for root in client.DEMO_BASES:
            for suffix in ("", "/"):
                with self.subTest(root=root, suffix=suffix):
                    os.environ["KALSHI_BASE"] = root + suffix
                    self.assertEqual(client.base_url(), root)

    def test_rejects_spoofed_hosts_paths_and_production_even_with_override(self):
        bad_roots = (
            "https://external-api.kalshi.com/trade-api/v2",
            "https://api.elections.kalshi.com/trade-api/v2",
            "https://external-api.kalshi.com/trade-api/v2?demo=1",
            "https://demo-api.example.org/trade-api/v2",
            "https://external-api.demo.kalshi.co.evil.invalid/trade-api/v2",
            "https://external-api.demo.kalshi.co@evil.invalid/trade-api/v2",
            "http://external-api.demo.kalshi.co/trade-api/v2",
            "https://external-api.demo.kalshi.co:443/trade-api/v2",
            "https://user:secret@external-api.demo.kalshi.co/trade-api/v2",
            client.DEFAULT_BASE + "?demo=1",
            client.DEFAULT_BASE + "#demo",
            client.DEFAULT_BASE + "/../v2",
            client.DEFAULT_BASE + "//",
            " " + client.DEFAULT_BASE,
            client.DEFAULT_BASE + "\n",
            "file:///tmp/demo",
            "",
        )
        for root in bad_roots:
            for override in ("", "1"):
                with self.subTest(root=root, override=override):
                    os.environ.update(KALSHI_BASE=root, KALSHI_ALLOW_PRODUCTION=override)
                    with self.assertRaises(SystemExit):
                        client.base_url()

    def test_rejected_base_is_not_echoed_or_signed(self):
        os.environ["KALSHI_BASE"] = "https://user:secret@demo.attacker.invalid"
        with patch.object(client, "load_key") as load, patch.object(client, "sign") as sign:
            with self.assertRaises(SystemExit) as raised:
                client.request("POST", "/portfolio/events/orders", {})
            self.assertNotIn("secret", str(raised.exception))
            self.assertNotIn("attacker", str(raised.exception))
            load.assert_not_called()
            sign.assert_not_called()

    def test_rejects_malformed_endpoint_before_loading_key(self):
        endpoints = ("https://evil.invalid/demo", "//evil.invalid/demo", "portfolio/balance",
                     "/portfolio/balance?limit=1", "/portfolio/balance#fragment",
                     "/portfolio/../orders", "/portfolio/./orders", "/portfolio/\\orders",
                     "/portfolio/\norders", "/portfolio/ orders")
        with patch.object(client, "load_key") as load:
            for endpoint in endpoints:
                with self.subTest(endpoint=endpoint), self.assertRaises(SystemExit):
                    client.request("GET", endpoint)
            load.assert_not_called()

    def test_signed_path_excludes_query_on_both_demo_roots(self):
        for root in client.DEMO_BASES:
            os.environ["KALSHI_BASE"] = root
            transport = FakeHTTPS()
            opener = urllib.request.build_opener(client.NoRedirects(), transport)
            with patch.object(client, "load_key", return_value=("fixture-id", object())), \
                 patch.object(client, "sign", return_value={}) as sign, \
                 patch.object(urllib.request, "build_opener", return_value=opener):
                self.assertEqual(client.request("GET", "/portfolio/fills", query="limit=5"),
                                 (200, {"ok": True}))
                self.assertEqual(sign.call_args.args[2:], ("GET", "/trade-api/v2/portfolio/fills"))
                self.assertEqual(transport.requests[0].full_url, root + "/portfolio/fills?limit=5")

    def test_redirects_never_forward_signed_headers_or_replay_orders(self):
        real_builder = urllib.request.build_opener
        for method in ("GET", "POST", "DELETE"):
            for status in (301, 302, 303, 307, 308):
                for destination in ("https://evil.invalid/steal", client.DEFAULT_BASE + "/other"):
                    with self.subTest(method=method, status=status, destination=destination):
                        transport = FakeHTTPS(status, b"redirect fixture", destination)

                        def builder(*handlers):
                            return real_builder(*handlers, transport)

                        with patch.object(client, "load_key", return_value=("fixture-id", object())), \
                             patch.object(client, "sign", return_value={"KALSHI-ACCESS-KEY": "fixture-id"}), \
                             patch.object(urllib.request, "build_opener", side_effect=builder):
                            code, _ = client.request(method, "/portfolio/events/orders",
                                                     {} if method == "POST" else None)
                        self.assertEqual(code, status)
                        self.assertEqual(len(transport.requests), 1)
                        self.assertEqual(transport.requests[0].host, "external-api.demo.kalshi.co")

    def test_http_error_and_non_json_still_reported_without_retry(self):
        for status, body, want in ((401, b'{"code":"unauthorized"}', {"code": "unauthorized"}),
                                   (503, b"unavailable", "unavailable")):
            transport = FakeHTTPS(status, body)
            opener = urllib.request.build_opener(client.NoRedirects(), transport)
            with patch.object(urllib.request, "build_opener", return_value=opener):
                self.assertEqual(client.request("GET", "/markets", auth=False), (status, want))
            self.assertEqual(len(transport.requests), 1)

    def place(self, **changes):
        params = dict(side="bid", ticker="FIXTURE-NOT-A-MARKET", count="2.50", price="0.4200",
                      tif="good_till_canceled", stp="taker_at_cross")
        params.update(changes)
        return client.place(**params)

    def test_invalid_order_inputs_never_reach_transport(self):
        inputs = (
            {"count": "0"}, {"count": "-1"}, {"count": "NaN"}, {"count": "Infinity"},
            {"count": "not a number"}, {"price": "NaN"}, {"price": "sNaN"},
            {"price": "-Infinity"}, {"price": "1"}, {"price": "0"}, {"price": "-0.1"},
            {"price": "0.42001"}, {"price": "0.99999"}, {"price": "0.00001"},
            {"side": "yes"}, {"ticker": ""}, {"ticker": "BAD\nTICKER"},
            {"tif": "GTT"}, {"stp": "none"},
        )
        with patch.object(client, "request") as request:
            for change in inputs:
                with self.subTest(change=change), self.assertRaises(SystemExit):
                    self.place(**change)
            request.assert_not_called()

    def test_valid_bid_ask_and_fractional_counts_preserve_values(self):
        for side in ("bid", "ask"):
            with patch.object(client, "request", return_value=(201, {"order_id": "fixture", "remaining_count": "2.50"})) as request, \
                 redirect_stdout(StringIO()):
                self.assertEqual(self.place(side=side), 0)
                request.assert_called_once()
                self.assertEqual(request.call_args.args, ("POST", "/portfolio/events/orders"))
                self.assertEqual(request.call_args.kwargs["body"], {
                    "ticker": "FIXTURE-NOT-A-MARKET", "side": side, "count": "2.50", "price": "0.4200",
                    "time_in_force": "good_till_canceled", "self_trade_prevention_type": "taker_at_cross",
                })

    def test_every_executive_table_row_has_an_official_reference(self):
        class Rows(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows, self.row, self.is_data = [], None, False

            def handle_starttag(self, tag, attrs):
                if tag == "tr":
                    self.row, self.is_data = [], False
                if tag == "td":
                    self.is_data = True
                if tag == "a" and self.row is not None:
                    self.row.append(dict(attrs).get("href", ""))

            def handle_endtag(self, tag):
                if tag == "tr" and self.row is not None:
                    if self.is_data:
                        self.rows.append(self.row)
                    self.row = None

        root = Path(__file__).resolve().parents[2]
        parser = Rows()
        parser.feed((root / "executive-summary.html").read_text())
        self.assertEqual(len(parser.rows), 27)  # 6 audit + 17 requirements + 4 fields
        for number, links in enumerate(parser.rows, 1):
            with self.subTest(row=number):
                self.assertTrue(any(link.startswith(("https://docs.kalshi.com/",
                                                      "https://help.kalshi.com/",
                                                      "https://docs.github.com/")) for link in links))

    def test_safety_finding_is_published_with_official_sources(self):
        root = Path(__file__).resolve().parents[2]
        findings = json.loads((root / "data/findings.json").read_text())
        row = next(x for x in findings["flagged"] if x["id"] == "SAFE-5C-01")
        self.assertIn("https://docs.kalshi.com/getting_started/demo_env", row["sources"])
        self.assertIn("no production override", row["action"])
        summary = (root / "executive-summary.html").read_text()
        self.assertIn('id="audit-2026-11-22"', summary)
        self.assertIn("SAFE-5C-01", summary)
        board = (root / "COORDINATION.md").read_text()
        self.assertIsNone(re.search(r"^(?:<{7} |={7}$|>{7} )", board, re.MULTILINE),
                          "coordination board contains unresolved merge markers")


if __name__ == "__main__":
    unittest.main()
