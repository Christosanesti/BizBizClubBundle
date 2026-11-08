#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
گیم سنتر — تست سرویس

Runs the real app.py in a subprocess against a throw-away data directory and
talks to it over HTTP, the same way the browser does. This is what catches
wiring bugs: a JSON field the UI sends but the server ignores, a route that
returns the wrong shape, a file it refuses to serve.
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="gc-http-"))
        cls.port = free_port()
        env = dict(os.environ, GAMECENTER_DATA=str(cls.tmp))
        cls.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "app.py"), "--port", str(cls.port), "--no-open"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if cls.req("GET", "/api/ping")[1].get("ok"):
                    return
            except OSError:
                time.sleep(0.1)
        cls.proc.kill()
        raise RuntimeError("server did not start: " + cls.proc.stderr.read().decode())

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def req(cls, method: str, path: str, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        try:
            payload = None if body is None else json.dumps(body).encode("utf-8")
            headers = {"Content-Type": "application/json"} if payload else {}
            conn.request(method, path, body=payload, headers=headers)
            res = conn.getresponse()
            raw = res.read()
            ctype = res.getheader("Content-Type") or ""
            if "json" in ctype:
                return res.status, json.loads(raw.decode("utf-8"))
            return res.status, raw
        finally:
            conn.close()

    def setUp(self):
        # every test starts from a known price list and an idle shop
        for console in ("1", "2", "3", "4"):
            self.post("/api/cancel", {"console": console})
        self.post("/api/settings", {
            "shop_name": "گیم سنتر", "rates": {"1": 80000, "2": 100000, "3": 120000, "4": 140000},
            "rounding": 5, "round_mode": "up", "min_minutes": 0,
            "drinks": [{"name": "دلستر", "price": 30000}],
        })

    def get(self, path):
        return self.req("GET", path)

    def post(self, path, body):
        return self.req("POST", path, body)

    # ────────────────────────────────────────────── static
    def test_serves_the_ui(self):
        status, html = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"app.js", html)
        status, js = self.get("/billing.js")
        self.assertEqual(status, 200)
        self.assertIn(b"GCBilling", js)

    def test_refuses_path_traversal(self):
        for path in ("/../app.py", "/%2e%2e/app.py", "/..%2fapp.py", "/vendor/../../app.py"):
            status, _ = self.get(path)
            self.assertEqual(status, 404, path)

    def test_unknown_api_is_404(self):
        self.assertEqual(self.post("/api/nope", {})[0], 404)

    # ────────────────────────────────────────────── money over the wire
    def test_start_stop_round_trip(self):
        status, r = self.post("/api/start", {"console": "1", "handles": 2})
        self.assertEqual(status, 200, r)
        run = r["running"]["1"]
        self.assertEqual(run["rate"], 100000)
        self.assertIsInstance(run["start_ms"], int)
        self.assertIn("server_ms", r)

        time.sleep(1.2)
        status, r = self.post("/api/stop", {"console": "1", "items": [], "op_id": "http-1"})
        self.assertEqual(status, 200, r)
        row = r["session"]
        # one second of play rounds up to the 5-minute step the shop configured
        self.assertIn(row["seconds"], (1, 2))
        self.assertEqual(row["minutes"], 5)
        self.assertEqual(row["play"], 8333)            # 100000 × 5 ÷ 60
        self.assertEqual(row["total"], row["play"])
        self.assertGreaterEqual(row["end_ms"], row["start_ms"] + 1000)
        self.assertEqual(r["state"]["running"], {})

    def test_retry_is_idempotent_over_http(self):
        self.post("/api/start", {"console": "2", "handles": 1})
        _, first = self.post("/api/stop", {"console": "2", "items": [], "op_id": "http-2"})
        _, second = self.post("/api/stop", {"console": "2", "items": [], "op_id": "http-2"})
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(first["session"]["id"], second["session"]["id"])

    def test_stop_when_idle_is_an_error(self):
        status, r = self.post("/api/stop", {"console": "3", "items": []})
        self.assertEqual(status, 400)
        self.assertFalse(r["ok"])

    def test_items_are_priced_server_side(self):
        self.post("/api/start", {"console": "4", "handles": 1})
        _, r = self.post("/api/stop", {"console": "4", "items": [
            {"name": "دلستر", "price": 30000, "qty": 2},
            {"name": "پیتزا", "price": "۱۲۰٬۰۰۰", "qty": 1},
        ]})
        row = r["session"]
        self.assertEqual(row["items_total"], 180000)
        self.assertEqual(row["total"], row["play"] + 180000)

    def test_manual_and_csv(self):
        now = time.time()
        start = time.strftime("%Y-%m-%dT%H:%M", time.localtime(now - 3600))
        end = time.strftime("%Y-%m-%dT%H:%M", time.localtime(now))
        _, r = self.post("/api/manual", {"console": "3", "handles": 4,
                                         "start": start, "end": end, "extra": 10000,
                                         "extra_name": "چیپس"})
        self.assertTrue(r["ok"], r)
        row = r["state"]["today"]["sessions"][-1]
        self.assertEqual(row["minutes"], 60)
        self.assertEqual(row["play"], 140000)
        self.assertEqual(row["total"], 150000)

        status, body = self.get("/api/export.csv")
        self.assertEqual(status, 200)
        text = body.decode("utf-8-sig")
        totals = r["state"]["today"]["totals"]
        self.assertIn(f"جمع کل,{totals['total']}", text)

    def test_settings_over_the_wire(self):
        _, r = self.post("/api/settings", {
            "shop_name": "تست HTTP", "rates": {"1": 90000, "2": 100000, "3": 120000, "4": 140000},
            "rounding": 15, "round_mode": "nearest", "min_minutes": 0,
            "drinks": [{"name": "آب", "price": 5000}],
        })
        s = r["state"]["settings"]
        self.assertEqual(s["shop_name"], "تست HTTP")
        self.assertEqual(s["rates"]["1"], 90000)
        self.assertEqual(s["rounding"], 15)
        self.assertEqual(s["round_mode"], "nearest")
        self.assertEqual(len(s["drinks"]), 1)

    def test_state_is_json_serialisable_and_complete(self):
        _, r = self.get("/api/state")
        for key in ("settings", "today", "running", "server_ms", "data_dir", "is_stale"):
            self.assertIn(key, r)
        self.assertIn("totals", r["today"])
        self.assertIn("jalali_long", r["today"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
