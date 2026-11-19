#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
گیم سنتر — تست حساب‌وکتاب

    python3 -m unittest discover -s tests -v

Three layers:
  1. the money math itself (rounding, rate × minutes ÷ 60, item lines);
  2. the same cases through ui/billing.js (Node) — screen and server must agree;
  3. the book: start/stop/manual/delete/close-day through the real functions,
     with a frozen clock, checking every row is internally consistent.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import billing  # noqa: E402

SETTINGS = {"rounding": 5, "round_mode": "up", "min_minutes": 0}


def st(**kw) -> dict:
    return {**SETTINGS, **kw}


# ══════════════════════════════════════════════════════ 1. money math
class RoundingTests(unittest.TestCase):
    def test_exact_keeps_every_second(self):
        self.assertAlmostEqual(billing.bill_minutes(90, st(round_mode="exact")), 1.5)
        self.assertAlmostEqual(billing.bill_minutes(61, st(round_mode="exact")), 61 / 60)

    def test_up_rounds_to_the_next_step(self):
        self.assertEqual(billing.bill_minutes(1, st(rounding=5, round_mode="up")), 5)
        self.assertEqual(billing.bill_minutes(5 * 60, st(rounding=5, round_mode="up")), 5)
        self.assertEqual(billing.bill_minutes(5 * 60 + 1, st(rounding=5, round_mode="up")), 10)
        self.assertEqual(billing.bill_minutes(25 * 60, st(rounding=10, round_mode="up")), 30)
        self.assertEqual(billing.bill_minutes(0, st(rounding=5, round_mode="up")), 0)

    def test_nearest_rounds_half_up_not_bankers(self):
        # 25 minutes on a 10-minute grid is exactly 2.5 steps.
        # Python's round() said 20, the browser said 30 — the books disagreed.
        self.assertEqual(billing.bill_minutes(25 * 60, st(rounding=10, round_mode="nearest")), 30)
        self.assertEqual(billing.bill_minutes(24 * 60, st(rounding=10, round_mode="nearest")), 20)
        self.assertEqual(billing.bill_minutes(26 * 60, st(rounding=10, round_mode="nearest")), 30)
        self.assertEqual(billing.bill_minutes(2.5 * 60, st(rounding=5, round_mode="nearest")), 5)
        self.assertEqual(billing.bill_minutes(7.5 * 60, st(rounding=5, round_mode="nearest")), 10)

    def test_minimum_time_floor(self):
        self.assertEqual(billing.bill_minutes(30, st(rounding=0, min_minutes=15)), 15)
        self.assertEqual(billing.bill_minutes(30 * 60, st(rounding=0, min_minutes=15)), 30)

    def test_zero_or_broken_step_means_exact(self):
        self.assertAlmostEqual(billing.bill_minutes(90, st(rounding=0)), 1.5)
        self.assertAlmostEqual(billing.bill_minutes(90, st(rounding=None)), 1.5)

    def test_negative_seconds_never_bill(self):
        self.assertEqual(billing.bill_minutes(-500, st()), 0)
        self.assertEqual(billing.play_cost(billing.bill_minutes(-500, st()), 100000), 0)

    def test_play_cost_is_rate_per_hour(self):
        self.assertEqual(billing.play_cost(60, 80000), 80000)
        self.assertEqual(billing.play_cost(30, 100000), 50000)
        self.assertEqual(billing.play_cost(90, 120000), 180000)
        self.assertEqual(billing.play_cost(0, 140000), 0)

    def test_play_cost_rounds_half_up(self):
        self.assertEqual(billing.play_cost(1.5, 60), 2)   # 1.5
        self.assertEqual(billing.play_cost(2.5, 60), 3)   # 2.5 (Python round → 2)
        self.assertEqual(billing.play_cost(0.5, 60), 1)
        self.assertEqual(billing.play_cost(1.49, 60), 1)

    def test_round2_is_half_up(self):
        self.assertEqual(billing.round2(1.005), 1.0)
        self.assertEqual(billing.round2(2.345), 2.35)
        self.assertEqual(billing.round2(90), 90.0)

    def test_rate_for_handles(self):
        s = {"rates": {"1": 80000, "2": 100000, "3": 120000, "4": 140000}}
        self.assertEqual(billing.rate_for(1, s), 80000)
        self.assertEqual(billing.rate_for(4, s), 140000)
        self.assertEqual(billing.rate_for(0, s), 80000)
        self.assertEqual(billing.rate_for(9, s), 140000)
        self.assertEqual(billing.rate_for("۲", s), 100000)
        self.assertEqual(billing.rate_for(None, s), 80000)


class PlanBillingTests(unittest.TestCase):
    """bill_plan: a session whose rate changed mid-way."""

    def test_single_leg_is_exactly_bill(self):
        settings = st(rounding=5, round_mode="up")
        legs = [{"from_ms": 0, "rate": 80000, "mode": "local", "handles": 2}]
        got = billing.bill_plan(legs, settings, 90 * 60 * 1000)
        want = billing.bill(90 * 60, 80000, settings)
        self.assertEqual(got["play"], want["play"])
        self.assertEqual(got["minutes"], want["minutes"])
        self.assertEqual(got["min_extra"], 0)
        self.assertEqual(len(got["legs"]), 1)

    def test_two_legs_sum_their_own_prices(self):
        # 30 min @ 100k + 30 min @ 140k, exact minutes, no rounding games
        settings = st(rounding=1, round_mode="exact")
        legs = [
            {"from_ms": 0, "rate": 100000, "mode": "local", "handles": 2},
            {"from_ms": 30 * 60 * 1000, "rate": 140000, "mode": "local", "handles": 4},
        ]
        got = billing.bill_plan(legs, settings, 60 * 60 * 1000)
        self.assertEqual(got["play"], 50000 + 70000)
        self.assertEqual(got["minutes"], 60)
        self.assertEqual([g["play"] for g in got["legs"]], [50000, 70000])
        self.assertEqual(got["legs"][1]["handles"], 4)

    def test_each_leg_keeps_the_shop_rounding(self):
        # 3 min then 3 min at 5-min round-up → 5 + 5 billed, not 10 once
        settings = st(rounding=5, round_mode="up")
        legs = [
            {"from_ms": 0, "rate": 60000},
            {"from_ms": 3 * 60 * 1000, "rate": 120000},
        ]
        got = billing.bill_plan(legs, settings, 6 * 60 * 1000)
        self.assertEqual(got["minutes"], 10)
        self.assertEqual(got["play"], billing.play_cost(5, 60000) + billing.play_cost(5, 120000))

    def test_minimum_time_charged_once_at_last_rate(self):
        settings = st(rounding=1, round_mode="exact", min_minutes=15)
        legs = [
            {"from_ms": 0, "rate": 60000},
            {"from_ms": 60 * 1000, "rate": 120000},
        ]
        got = billing.bill_plan(legs, settings, 120 * 1000)  # 1 + 1 min
        self.assertEqual(got["minutes"], 15)
        # 2 billed minutes at their rates + 13 topped up at the last rate
        want = billing.play_cost(1, 60000) + billing.play_cost(1, 120000) + billing.play_cost(13, 120000)
        self.assertEqual(got["play"], want)
        self.assertEqual(got["min_extra"], 13)

    def test_junk_legs_are_skipped(self):
        settings = st()
        got = billing.bill_plan([None, "x", {"rate": 5}, {"from_ms": "bad"},
                                 {"from_ms": 0, "rate": 80000}], settings, 60000)
        self.assertEqual(got["play"], billing.bill(60, 80000, settings)["play"])

    def test_empty_plan_bills_zero(self):
        got = billing.bill_plan([], st(), 0)
        self.assertEqual(got["play"], 0)
        self.assertEqual(got["minutes"], 0)


class NumParseTests(unittest.TestCase):
    def test_digit_sets(self):
        self.assertEqual(billing.num("۱۰۰٬۰۰۰"), 100000)
        self.assertEqual(billing.num("١٠٠٠٠٠"), 100000)
        self.assertEqual(billing.num("100,000"), 100000)
        self.assertEqual(billing.num("100 000"), 100000)
        self.assertEqual(billing.num(100000), 100000)

    def test_edges(self):
        self.assertEqual(billing.num(None, 7), 7)
        self.assertEqual(billing.num("", 7), 7)
        self.assertEqual(billing.num("abc", 7), 7)
        self.assertEqual(billing.num("-", 7), 7)
        self.assertEqual(billing.num("-5000"), -5000)
        self.assertEqual(billing.num(2.5), 3)      # half-up, like the browser
        self.assertEqual(billing.num(True), 1)


class ItemTests(unittest.TestCase):
    def test_normalise_items(self):
        got = billing.normalise_items([
            {"name": "دلستر", "price": 30000, "qty": 2},
            {"name": "  ", "price": 1000},
            {"name": "چیپس", "price": -1, "qty": 1},
            {"name": "پفک", "price": 15000, "qty": 0},
            {"name": "بستنی", "price": 30000, "qty": 500},
            "not-a-dict",
        ])
        self.assertEqual(got, [
            {"name": "دلستر", "price": 30000, "qty": 2},
            {"name": "بستنی", "price": 30000, "qty": billing.MAX_ITEM_QTY},
        ])
        self.assertEqual(billing.items_total(got), 60000 + 30000 * billing.MAX_ITEM_QTY)

    def test_items_total_ignores_junk(self):
        self.assertEqual(billing.items_total(None), 0)
        self.assertEqual(billing.items_total([{"name": "x", "price": "۵٬۰۰۰", "qty": "۳"}]), 15000)


class DayTotalsTests(unittest.TestCase):
    def test_totals_are_the_sum_of_rows(self):
        day = {"sessions": [
            {"play": 1000, "items_total": 500},
            {"play": 2000, "items_total": 0},
            {"play": 0, "items_total": 2500},
        ]}
        self.assertEqual(billing.day_totals(day),
                         {"count": 3, "play": 3000, "items": 3000, "total": 6000})

    def test_empty(self):
        self.assertEqual(billing.day_totals({"sessions": []}),
                         {"count": 0, "play": 0, "items": 0, "total": 0})


# ══════════════════════════════════════════ 2. screen == server (Node)
def parity_cases() -> list[dict]:
    rnd = random.Random(20261108)
    modes = ["up", "nearest", "exact"]
    steps = [0, 1, 5, 10, 15, 30, 60]
    rates = [0, 10000, 80000, 95000, 100000, 120000, 140000, 175000]
    cases = []
    for mode in modes:
        for step in steps:
            for sec in (0, 1, 59, 60, 61, 299, 300, 301, 899, 900, 901,
                        1500, 1499, 1800, 2700, 3599, 3600, 3601, 7200, 25 * 60,
                        1234.567, 12345.678, 86400):
                cases.append({
                    "sec": sec,
                    "rate": rates[len(cases) % len(rates)],
                    "settings": {"rounding": step, "round_mode": mode,
                                 "min_minutes": 0 if step % 2 else 15},
                })
    for _ in range(300):
        cases.append({
            "sec": rnd.uniform(0, 3 * 3600),
            "rate": rnd.choice(rates),
            "settings": {"rounding": rnd.choice(steps), "round_mode": rnd.choice(modes),
                         "min_minutes": rnd.choice([0, 0, 5, 15, 30])},
        })
    # multi-leg plans: rate/mode changes mid-session must bill identically
    # on both sides of the mirror
    for _ in range(120):
        n = rnd.choice([2, 2, 3, 4])
        bounds = sorted(rnd.sample(range(1, 600), n - 1))
        legs = []
        for i, cut in enumerate([0] + bounds):
            legs.append({
                "from_ms": cut * 10000,
                "rate": rnd.choice(rates),
                "mode": "plus" if rnd.random() < .3 else "local",
                "handles": rnd.randint(1, 4),
            })
        cases.append({
            "sec": 0, "rate": 0,
            "legs": legs, "end_ms": 600 * 10000,
            "settings": {"rounding": rnd.choice(steps), "round_mode": rnd.choice(modes),
                         "min_minutes": rnd.choice([0, 0, 5, 15, 30])},
        })
    return cases


class JavaScriptParityTests(unittest.TestCase):
    """The UI must show exactly the number the server will record."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        cls.cases = parity_cases()
        cls.js = None
        if cls.node:
            proc = subprocess.run(
                [cls.node, str(ROOT / "tests" / "js_parity.js")],
                input=json.dumps(cls.cases),  # ensure_ascii=True → pure ASCII
                capture_output=True, encoding="utf-8", errors="replace", timeout=120,
            )
            if proc.returncode != 0:
                raise AssertionError(f"node failed: {proc.stderr}")
            cls.js = json.loads(proc.stdout)

    def setUp(self):
        if not self.node:
            self.skipTest("node not installed")
        self.assertEqual(len(self.js), len(self.cases))

    def test_identical_numbers(self):
        for case, js in zip(self.cases, self.js):
            py = billing.bill(case["sec"], case["rate"], case["settings"])
            self.assertAlmostEqual(
                js["billMinutes"], billing.bill_minutes(case["sec"], case["settings"]),
                places=9, msg=f"billMinutes {case}")
            self.assertEqual(js["minutes"], py["minutes"], f"minutes {case}")
            self.assertEqual(js["play"], py["play"], f"play {case}")

    def test_plan_identical_numbers(self):
        for case, js in zip(self.cases, self.js):
            if "legs" not in case:
                continue
            py = billing.bill_plan(case["legs"], case["settings"], case["end_ms"])
            self.assertAlmostEqual(js["plan"]["minutes"], py["minutes"], places=9,
                                   msg=f"plan minutes {case}")
            self.assertEqual(js["plan"]["play"], py["play"], f"plan play {case}")
            self.assertEqual(js["plan"]["legs"], len(py["legs"]), f"plan legs {case}")
            self.assertAlmostEqual(js["plan"]["min_extra"], py["min_extra"], places=9,
                                   msg=f"plan min_extra {case}")

    def test_identical_display(self):
        for case, js in zip(self.cases, self.js):
            minutes = billing.bill(case["sec"], case["rate"], case["settings"])["minutes"]
            want = str(int(minutes)) if float(minutes).is_integer() else f"{minutes:.2f}"
            if "." in want:
                want = want.rstrip("0").rstrip(".")
            want = want.replace(".", "٫")
            want = "".join("۰۱۲۳۴۵۶۷۸۹"[int(c)] if c.isdigit() else c for c in want)
            self.assertEqual(
                js["fmtMinutes"], want,
                f"fmtMinutes {case} — js={[hex(ord(c)) for c in js['fmtMinutes']]} "
                f"py={[hex(ord(c)) for c in want]}",
            )


# ══════════════════════════════════════════════════════ 3. the book
class Clock:
    def __init__(self, start: dt.datetime):
        self.t = start

    def now(self) -> dt.datetime:
        return self.t.replace(microsecond=0)

    def now_ms(self) -> int:
        return int(round(self.t.timestamp() * 1000))

    def advance(self, seconds: float) -> None:
        self.t += dt.timedelta(seconds=seconds)


class BookTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gc-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "days").mkdir()
        self.clock = Clock(dt.datetime(2026, 11, 8, 18, 0, 0))
        for target, value in (
            ("DATA_DIR", self.tmp),
            ("DAYS_DIR", self.tmp / "days"),
            ("STATE_FILE", self.tmp / "running.json"),
            ("SETTINGS_FILE", self.tmp / "settings.json"),
            ("now", self.clock.now),
            ("now_ms", self.clock.now_ms),
        ):
            p = mock.patch.object(app, target, value)
            p.start()
            self.addCleanup(p.stop)
        app.save_json(app.SETTINGS_FILE, app.DEFAULT_SETTINGS)

    def use_settings(self, **kw):
        app.op_update_settings({
            "shop_name": "گیم سنتر",
            "rates": app.DEFAULT_SETTINGS["rates"],
            "rounding": kw.get("rounding", 5),
            "round_mode": kw.get("round_mode", "up"),
            "min_minutes": kw.get("min_minutes", 0),
            "drinks": app.DEFAULT_SETTINGS["drinks"],
        })

    def rows(self):
        return app.current_day()["sessions"]

    def settle(self, seconds: float, console: str = "1", items=None, op_id: str = ""):
        """Let the wall clock run, then settle at that exact millisecond —
        the same thing the UI does when the cashier presses the button."""
        self.clock.advance(seconds)
        return app.op_stop(console, items or [], end_ms=self.clock.now_ms(), op_id=op_id)


class StartStopTests(BookTestCase):
    def test_start_snapshots_rate_and_clock(self):
        app.op_start("1", 3)
        run = app.load_state()["1"]
        self.assertEqual(run["handles"], 3)
        self.assertEqual(run["rate"], 120000)
        self.assertEqual(run["start_ms"], self.clock.now_ms())

    def test_double_start_is_refused(self):
        app.op_start("1", 2)
        with self.assertRaises(ValueError):
            app.op_start("1", 2)

    def test_stop_bills_the_elapsed_time(self):
        app.op_start("1", 3)
        row = self.settle(90 * 60)["session"]
        self.assertEqual(row["minutes"], 90)
        self.assertEqual(row["play"], 180000)       # 120000/h × 1.5h
        self.assertEqual(row["total"], 180000)
        self.assertEqual(row["start_ms"] + 90 * 60 * 1000, row["end_ms"])
        self.assertEqual(app.load_state(), {})

    def test_stop_with_drinks_and_custom_items(self):
        app.op_start("2", 2)
        items = [
            {"name": "دلستر", "price": 30000, "qty": 2},
            {"name": "پیتزا", "price": 120000, "qty": 1},
            {"name": "", "price": 9999, "qty": 1},
            {"name": "چیپس", "price": 20000, "qty": -3},
        ]
        row = self.settle(60 * 60, console="2", items=items)["session"]
        self.assertEqual(row["play"], 100000)
        self.assertEqual(row["items_total"], 180000)
        self.assertEqual(row["total"], 280000)
        self.assertEqual(len(row["items"]), 2)

    def test_settlement_uses_the_instant_the_ui_showed(self):
        app.op_start("1", 1)
        # the UI freezes the clock on click and posts that exact millisecond
        self.clock.advance(123.456)
        end = self.clock.now_ms()
        row = app.op_stop("1", [], end_ms=end)["session"]
        self.assertEqual(row["end_ms"], end)
        want = billing.bill((end - row["start_ms"]) / 1000, row["rate"], app.get_settings())
        self.assertEqual(row["minutes"], want["minutes"])
        self.assertEqual(row["play"], want["play"])

    def test_rate_change_mid_session_does_not_change_the_bill(self):
        app.op_start("1", 1)                      # 80,000/h
        self.use_settings()                       # still 80,000
        app.save_json(app.SETTINGS_FILE, {**app.DEFAULT_SETTINGS,
                                          "rates": {"1": 500000, "2": 500000, "3": 500000, "4": 500000}})
        row = self.settle(60 * 60)["session"]
        self.assertEqual(row["rate"], 80000)
        self.assertEqual(row["play"], 80000)

    def test_future_end_is_clamped_to_now(self):
        app.op_start("1", 1)
        row = app.op_stop("1", [], end_ms=self.clock.now_ms() + 10**9)["session"]
        self.assertEqual(row["end_ms"], self.clock.now_ms() + 2000)

    def test_end_before_start_is_clamped_to_zero(self):
        app.op_start("1", 1)
        row = app.op_stop("1", [], end_ms=self.clock.now_ms() - 10**9)["session"]
        self.assertEqual(row["end_ms"], row["start_ms"])
        self.assertEqual(row["seconds"], 0)
        self.assertEqual(row["play"], 0)

    def test_garbage_end_falls_back_to_server_clock(self):
        app.op_start("1", 1)
        row = app.op_stop("1", [], end_ms="banana")["session"]
        self.assertGreaterEqual(row["end_ms"], row["start_ms"])

    def test_retried_settle_does_not_double_bill(self):
        app.op_start("1", 2)
        first = self.settle(30 * 60, op_id="op-1")
        second = app.op_stop("1", [], end_ms=self.clock.now_ms(), op_id="op-1")
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(first["session"]["id"], second["session"]["id"])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(app.public_state()["today"]["totals"]["total"], 50000)

    def test_stop_without_start_is_refused(self):
        with self.assertRaises(ValueError):
            app.op_stop("4", [])

    def test_cancel_records_nothing(self):
        app.op_start("3", 1)
        app.op_cancel("3")
        self.assertEqual(self.rows(), [])
        self.assertEqual(app.load_state(), {})

    def test_running_state_exposes_ms_clock(self):
        app.op_start("1", 1)
        state = app.public_state()
        self.assertEqual(state["running"]["1"]["start_ms"], self.clock.now_ms())
        self.assertIn("server_ms", state)
        self.assertEqual(state["running"]["1"]["start_label"], "۱۸:۰۰")


class RoundingSettlementTests(BookTestCase):
    def _settle(self, minutes: float, **settings):
        self.use_settings(**settings)
        app.op_start("1", 1)                     # 80,000/h
        return self.settle(minutes * 60)["session"]

    def test_nearest_ten_minutes(self):
        row = self._settle(25, rounding=10, round_mode="nearest")
        self.assertEqual(row["minutes"], 30)
        self.assertEqual(row["play"], billing.play_cost(30, 80000))

    def test_up_five_minutes(self):
        row = self._settle(1, rounding=5, round_mode="up")
        self.assertEqual(row["minutes"], 5)
        self.assertEqual(row["play"], 6667)      # 80000×5/60 = 6666.67 → 6667

    def test_exact(self):
        row = self._settle(90.5, rounding=1, round_mode="exact")
        self.assertEqual(row["minutes"], 90.5)
        self.assertEqual(row["play"], billing.play_cost(90.5, 80000))

    def test_minimum_charge(self):
        row = self._settle(2, rounding=0, round_mode="exact", min_minutes=15)
        self.assertEqual(row["minutes"], 15)
        self.assertEqual(row["play"], 20000)


class PlanSessionTests(BookTestCase):
    """Mid-game plan changes: handles 1–4 and online (Plus)."""

    def test_plus_start_uses_plus_rate(self):
        app.op_update_settings({"plus_rate": 50000})
        app.op_start("1", 2, mode="plus")
        run = app.load_state()["1"]
        self.assertEqual(run["mode"], "plus")
        self.assertEqual(run["rate"], 50000)
        row = self.settle(60 * 60)["session"]
        self.assertEqual(row["mode"], "plus")
        self.assertEqual(row["play"], 50000)
        self.assertEqual(app.plan_label(row), "Plus")

    def test_plan_change_splits_the_bill(self):
        app.op_start("1", 2)                       # 100,000/h
        self.clock.advance(30 * 60)
        app.op_plan("1", "local", 4)               # → 140,000/h
        self.clock.advance(30 * 60)
        end = self.clock.now_ms()
        row = app.op_stop("1", [], end_ms=end)["session"]
        # exact-mode-free default settings: 5-min step, both legs land on 30
        self.assertEqual(row["play"], 50000 + 70000)
        self.assertEqual(row["minutes"], 60)
        self.assertEqual(row["mode"], "local")
        self.assertEqual(row["handles"], 4)
        self.assertEqual(len(row["segments"]), 2)
        self.assertEqual([g["rate"] for g in row["segments"]], [100000, 140000])
        self.assertEqual(app.plan_label(row), "2+4")

    def test_switch_to_plus_and_back(self):
        app.op_update_settings({"plus_rate": 50000})
        app.op_start("1", 1)                       # 80,000/h
        self.clock.advance(10 * 60)
        app.op_plan("1", "plus", 1)
        self.clock.advance(10 * 60)
        app.op_plan("1", "local", 3)               # 120,000/h
        self.clock.advance(10 * 60)
        row = self.settle(0)["session"]
        # 10 min legs at 5-min rounding → 10 billed each
        self.assertEqual(row["play"],
                         billing.play_cost(10, 80000) + billing.play_cost(10, 50000)
                         + billing.play_cost(10, 120000))
        self.assertEqual(app.plan_label(row), "1+Plus+3")
        self.assertEqual(len(app.load_state()), 0)

    def test_same_plan_is_a_noop(self):
        app.op_start("1", 2)
        before = app.load_state()["1"]["legs"]
        app.op_plan("1", "local", 2)
        self.assertEqual(app.load_state()["1"]["legs"], before)
        app.op_plan("1", "plus", 2)
        app.op_plan("1", "plus", 3)                # handles ignored in plus mode
        self.assertEqual(len(app.load_state()["1"]["legs"]), 2)

    def test_plan_on_idle_console_is_refused(self):
        with self.assertRaises(ValueError):
            app.op_plan("2", "plus", 1)

    def test_running_state_exposes_legs(self):
        app.op_start("1", 2)
        self.clock.advance(60)
        app.op_plan("1", "local", 3)
        run = app.public_state()["running"]["1"]
        self.assertEqual(run["mode"], "local")
        self.assertEqual(run["handles"], 3)
        self.assertEqual(len(run["legs"]), 2)
        self.assertEqual(run["legs"][1]["rate"], 120000)

    def test_legacy_running_state_without_legs_still_bills(self):
        app.op_start("1", 2)
        st = app.load_state()
        st["1"].pop("legs")
        st["1"].pop("mode", None)
        app.save_state(st)
        row = self.settle(60 * 60)["session"]
        self.assertEqual(row["play"], 100000)
        self.assertEqual(row["mode"], "local")

    def test_manual_plus_entry(self):
        app.op_update_settings({"plus_rate": 50000})
        start = self.clock.now() - dt.timedelta(minutes=60)
        app.op_manual({"console": "1", "mode": "plus", "handles": 2,
                       "start": start.isoformat(timespec="minutes"),
                       "end": self.clock.now().isoformat(timespec="minutes")})
        row = self.rows()[0]
        self.assertEqual(row["mode"], "plus")
        self.assertEqual(row["rate"], 50000)
        self.assertEqual(row["play"], 50000)
        self.assertEqual(app.plan_label(row), "Plus")

    def test_plus_rate_in_settings_round_trip(self):
        app.op_update_settings({"plus_rate": "۷۵٬۰۰۰"})
        self.assertEqual(app.get_settings()["plus_rate"], 75000)
        s = app.op_update_settings({"plus_rate": -10})["settings"]
        self.assertEqual(s["plus_rate"], 0)


class ManualEntryTests(BookTestCase):
    def payload(self, **kw):
        start = self.clock.now() - dt.timedelta(minutes=90)
        p = {"console": "2", "handles": 3,
             "start": start.isoformat(timespec="minutes"),
             "end": self.clock.now().isoformat(timespec="minutes"),
             "extra": 0, "extra_name": "", "note": ""}
        p.update(kw)
        return p

    def test_manual_matches_the_same_formula(self):
        app.op_manual(self.payload(extra=45000, extra_name="هله‌هوله"))
        row = self.rows()[0]
        self.assertEqual(row["minutes"], 90)
        self.assertEqual(row["play"], 180000)
        self.assertEqual(row["items_total"], 45000)
        self.assertEqual(row["total"], 225000)
        self.assertTrue(row["manual"])

    def test_manual_rejects_backwards_time(self):
        with self.assertRaises(ValueError):
            app.op_manual(self.payload(end=(self.clock.now() - dt.timedelta(hours=2)).isoformat()))

    def test_manual_rejects_the_future(self):
        with self.assertRaises(ValueError):
            app.op_manual(self.payload(end=(self.clock.now() + dt.timedelta(hours=2)).isoformat()))

    def test_manual_rejects_more_than_a_day(self):
        with self.assertRaises(ValueError):
            app.op_manual(self.payload(start=(self.clock.now() - dt.timedelta(hours=30)).isoformat()))

    def test_manual_rejects_garbage(self):
        with self.assertRaises(ValueError):
            app.op_manual(self.payload(start="not-a-date"))

    def test_manual_note_and_extra(self):
        app.op_manual(self.payload(extra="۵۰٬۰۰۰", extra_name="  بستنی  ", note="مهمان"))
        row = self.rows()[0]
        self.assertEqual(row["items"][0], {"name": "بستنی", "price": 50000, "qty": 1})
        self.assertEqual(row["note"], "مهمان")


class BookkeepingTests(BookTestCase):
    def _one_session(self, minutes=60, handles=2):
        app.op_start("1", handles)
        self.settle(minutes * 60, items=[{"name": "دلستر", "price": 30000, "qty": 1}])

    def test_every_row_is_internally_consistent(self):
        app.op_start("1", 2)
        self.settle(73 * 60, items=[{"name": "چای", "price": 15000, "qty": 3}])
        row = self.rows()[0]
        self.assertEqual(row["total"], row["play"] + row["items_total"])
        self.assertEqual(row["play"], billing.play_cost(row["minutes"], row["rate"]))
        self.assertEqual(row["items_total"], 45000)
        self.assertEqual(row["end_ms"] - row["start_ms"], 73 * 60 * 1000)

    def test_day_totals_match_the_footer(self):
        self._one_session(60, 2)                 # 100000
        self._one_session(30, 1)                 # 40000 + 30000
        totals = app.public_state()["today"]["totals"]
        rows = self.rows()
        self.assertEqual(totals["count"], 2)
        self.assertEqual(totals["play"], sum(r["play"] for r in rows))
        self.assertEqual(totals["items"], sum(r["items_total"] for r in rows))
        self.assertEqual(totals["total"], totals["play"] + totals["items"])
        self.assertEqual(totals["play"], 100000 + 40000)
        self.assertEqual(totals["items"], 60000)

    def test_delete_updates_totals(self):
        self._one_session(60, 2)
        before = app.public_state()["today"]["totals"]["total"]
        app.op_delete(self.rows()[0]["id"])
        self.assertEqual(self.rows(), [])
        self.assertEqual(app.public_state()["today"]["totals"]["total"], 0)
        self.assertEqual(before, 130000)
        with self.assertRaises(ValueError):
            app.op_delete("nope")

    def test_close_day_archives_and_resets(self):
        self._one_session(60, 2)
        total = app.public_state()["today"]["totals"]["total"]
        out = app.op_close_day()
        self.assertEqual(out["summary"]["total"], total)
        archived = json.loads((self.tmp / "days" / out["file"]).read_text(encoding="utf-8"))
        self.assertEqual(billing.day_totals(archived)["total"], total)
        self.assertEqual(self.rows(), [])
        self.assertEqual(app.public_state()["today"]["totals"]["total"], 0)

    def test_close_day_refuses_while_a_console_runs(self):
        app.op_start("1", 1)
        with self.assertRaises(ValueError):
            app.op_close_day()

    def test_close_day_refuses_an_empty_book(self):
        with self.assertRaises(ValueError):
            app.op_close_day()

    def test_archive_files_never_collide(self):
        self._one_session(60, 1)
        a = app.op_close_day()["file"]
        self._one_session(60, 1)
        b = app.op_close_day()["file"]
        self.assertNotEqual(a, b)
        self.assertTrue((self.tmp / "days" / a).is_file())
        self.assertTrue((self.tmp / "days" / b).is_file())

    def test_csv_totals_match_the_book(self):
        self._one_session(60, 2)
        text = app.day_csv().decode("utf-8-sig")
        totals = app.public_state()["today"]["totals"]
        self.assertIn(f"جمع بازی,{totals['play']}", text)
        self.assertIn(f"جمع نوشیدنی,{totals['items']}", text)
        self.assertIn(f"جمع کل,{totals['total']}", text)

    def test_settings_round_trip_and_clamp(self):
        app.op_update_settings({"shop_name": "  تست  ", "rates": {"1": "۹۵٬۰۰۰", "2": -5, "3": 0, "4": 140000},
                                "rounding": -3, "round_mode": "weird", "min_minutes": "۱۵",
                                "drinks": [{"name": "آب", "price": "۵۰۰۰"}, {"name": "", "price": 1}]})
        s = app.get_settings()
        self.assertEqual(s["shop_name"], "تست")
        self.assertEqual(s["rates"]["1"], 95000)
        self.assertEqual(s["rates"]["2"], 0)      # clamped, not negative
        self.assertEqual(s["rounding"], 0)
        self.assertEqual(s["round_mode"], "up")   # invalid mode ignored
        self.assertEqual(s["min_minutes"], 15)
        self.assertEqual(s["drinks"], [{"name": "آب", "price": 5000}])

    def test_settings_survive_a_restart(self):
        self.use_settings(rounding=15, round_mode="nearest")
        self.assertEqual(app.get_settings()["rounding"], 15)
        self.assertEqual(app.get_settings()["round_mode"], "nearest")

    def test_state_file_is_valid_json_after_every_operation(self):
        self._one_session(60, 2)
        for p in (self.tmp / "running.json", self.tmp / "days" / "current.json",
                  self.tmp / "settings.json"):
            self.assertTrue(p.is_file(), p)
            json.loads(p.read_text(encoding="utf-8"))


class JalaliTests(unittest.TestCase):
    def test_known_dates(self):
        cases = {
            (2026, 3, 21): (1405, 1, 1),
            (2026, 11, 8): (1405, 8, 17),
            (2026, 9, 22): (1405, 6, 31),
            (2025, 12, 31): (1404, 10, 10),
        }
        for (gy, gm, gd), want in cases.items():
            self.assertEqual(app.jalali_parts(dt.date(gy, gm, gd)), want)

    def test_weekday_names(self):
        self.assertEqual(app.jalali_full(dt.date(2026, 11, 8)).split()[0], "یکشنبه")
        self.assertEqual(app.jalali_full(dt.date(2026, 11, 7)).split()[0], "شنبه")


if __name__ == "__main__":
    unittest.main(verbosity=2)
