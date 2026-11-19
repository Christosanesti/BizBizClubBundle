#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
گیم سنتر — حساب‌وکتاب

The single source of truth for every number that ends up in the day book:

    seconds → billed minutes → play cost
    items  → items total
    rows   → day totals

`ui/billing.js` is the exact JavaScript mirror of this module (the UI has to
show the same number the server will record). Both sides use round-half-up on
IEEE doubles, so `tests/test_billing.py` can compare them case by case.

Formula:  cost = rate (per hour) × billed minutes ÷ 60
"""
from __future__ import annotations

import math
import re

DIGIT_TABLE = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

MAX_HANDLES = 4
MAX_ITEM_QTY = 99
MAX_SESSION_SECONDS = 24 * 3600


def round_half_up(x: float) -> int:
    """Round .5 away from zero — the same rule as JavaScript's Math.round.

    Python's built-in round() is banker's rounding (2.5 → 2), which silently
    disagreed with the browser (2.5 → 3) and put different money in the book
    than the cashier saw on screen.
    """
    x = float(x)
    if x != x:  # NaN
        return 0
    return int(math.floor(x + 0.5))


def num(v, default: int = 0) -> int:
    """Parse a number the way a Persian keyboard would send it.

    Accepts ۱۰۰٬۰۰۰, 100,000, "100 000", 100000 and plain ints — never
    silently turns a value into 0 because of a different digit set.
    """
    try:
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return round_half_up(v)
        s = re.sub(r"[^0-9\-]", "", str(v).translate(DIGIT_TABLE))
        if s in ("", "-"):
            return default
        return int(s)
    except Exception:
        return default


def round2(x: float) -> float:
    """Two decimals, half-up — matches `Math.round(x * 100) / 100`."""
    return math.floor(float(x) * 100 + 0.5) / 100


def bill_minutes(seconds: float, settings: dict) -> float:
    """Turn elapsed seconds into the minutes the shop charges for."""
    raw = max(0.0, float(seconds)) / 60.0
    step = num(settings.get("rounding"), 0)
    mode = settings.get("round_mode") or "up"
    if step <= 0 or mode == "exact":
        m = raw
    elif mode == "nearest":
        m = math.floor(raw / step + 0.5) * step
    else:  # "up"
        m = math.ceil(raw / step) * step
    floor_min = float(num(settings.get("min_minutes"), 0))
    return max(m, floor_min)


def play_cost(minutes: float, rate: int) -> int:
    """rate is per hour; minutes is the billed duration."""
    return round_half_up((num(rate) * float(minutes)) / 60.0)


def rate_for(handles, settings: dict) -> int:
    """Hourly price for 1–4 handles; anything odd falls back to one handle."""
    h = max(1, min(MAX_HANDLES, num(handles, 1) or 1))
    return num((settings.get("rates") or {}).get(str(h), 0))


def bill(seconds: float, rate: int, settings: dict) -> dict:
    """The one function both the live timer and the receipt use."""
    minutes = round2(bill_minutes(seconds, settings))
    play = play_cost(minutes, rate)
    return {"seconds": max(0.0, float(seconds)), "minutes": minutes, "play": play}


def bill_plan(legs, settings: dict, end_ms) -> dict:
    """Bill a session whose rate changed mid-way (handles or Plus toggled).

    legs: chronological [{'from_ms', 'rate', 'mode'?, 'handles'?}, ...] — the
    last leg is still open and runs until end_ms. Each leg is billed on its
    own with the shop's rounding rules, so time at ۲ دسته and time at Plus are
    two honest stretches, not an average. The minimum-time floor applies once
    to the whole session and is charged at the last leg's rate.

    A single leg returns exactly what bill() returns — one rate, one stretch —
    so every session that never changed plan bills byte-for-byte as before.
    """
    clean = []
    for l in legs if isinstance(legs, list) else []:
        if not isinstance(l, dict):
            continue
        frm = num(l.get("from_ms"), -1)
        if frm < 0:
            continue
        clean.append({**l, "from_ms": frm, "rate": num(l.get("rate"), 0)})
    if not clean:
        clean = [{"from_ms": 0, "rate": 0}]
    end = num(end_ms, 0)
    n = len(clean)

    def bounds(i: int):
        frm = clean[i]["from_ms"]
        raw_to = clean[i + 1]["from_ms"] if i + 1 < n else end
        return frm, max(frm, min(raw_to, end))

    detail = []
    if n == 1:
        frm, to = bounds(0)
        sec = max(0.0, (to - frm) / 1000.0)
        b = bill(sec, clean[0]["rate"], settings)
        detail.append({**{k: clean[0].get(k) for k in ("mode", "handles")},
                       "rate": clean[0]["rate"], "from_ms": frm, "to_ms": to,
                       "seconds": b["seconds"], "minutes": b["minutes"], "play": b["play"]})
        return {"seconds": b["seconds"], "minutes": b["minutes"], "play": b["play"],
                "legs": detail, "min_extra": 0.0}

    nofloor = dict(settings)
    nofloor["min_minutes"] = 0
    total_min = 0.0
    play = 0
    seconds = 0.0
    for i, leg in enumerate(clean):
        frm, to = bounds(i)
        sec = max(0.0, (to - frm) / 1000.0)
        minutes = round2(bill_minutes(sec, nofloor))
        p = play_cost(minutes, leg["rate"])
        detail.append({**{k: leg.get(k) for k in ("mode", "handles")},
                       "rate": leg["rate"], "from_ms": frm, "to_ms": to,
                       "seconds": sec, "minutes": minutes, "play": p})
        total_min += minutes
        play += p
        seconds += sec
    total_min = round2(total_min)
    deficit = max(0.0, float(num(settings.get("min_minutes"), 0)) - total_min)
    min_play = play_cost(deficit, clean[-1]["rate"]) if deficit > 0 else 0
    return {"seconds": seconds, "minutes": round2(total_min + deficit),
            "play": play + min_play, "legs": detail, "min_extra": deficit}


def normalise_items(items) -> list:
    """Keep only sellable lines; caps quantity so a typo can't invent stock."""
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "")).strip()[:60]
        if not name:
            continue
        price = num(it.get("price", 0), -1)
        qty = num(it.get("qty", 1), 0)
        if qty <= 0 or price < 0:
            continue
        out.append({"name": name, "price": price, "qty": min(qty, MAX_ITEM_QTY)})
    return out


def items_total(items) -> int:
    return sum(i["price"] * i["qty"] for i in normalise_items(items))


def day_totals(day: dict) -> dict:
    """Totals are derived, never stored-and-trusted: sum the rows."""
    ss = day.get("sessions", []) if isinstance(day, dict) else []
    play = sum(num(s.get("play"), 0) for s in ss)
    items = sum(num(s.get("items_total"), 0) for s in ss)
    return {"count": len(ss), "play": play, "items": items, "total": play + items}
