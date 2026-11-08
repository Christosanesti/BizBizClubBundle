#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
گیم‌سنتر — دفتر روزانه باشگاه بازی
Local bookkeeping server. Serves the UI and stores everything as plain JSON
files under ~/.local/share/gamecenter so nothing is ever lost in a browser store.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from billing import (
    MAX_SESSION_SECONDS,
    bill,
    day_totals,
    normalise_items,
    num,
    rate_for,
    round_half_up,
)

FROZEN = bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Where the UI lives — inside the PyInstaller bundle, or next to the app."""
    here = Path(__file__).resolve().parent
    if not FROZEN:
        return here
    bundle = Path(getattr(sys, "_MEIPASS", here))
    # an editable ui/ folder next to the .exe wins over the bundled copy
    beside = Path(sys.executable).resolve().parent / "ui"
    return beside if (beside / "index.html").is_file() else bundle


def default_data_dir() -> Path:
    env = os.environ.get("GAMECENTER_DATA")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return Path(base) / "GameCenter" if base else Path.home() / "GameCenter"
    return Path.home() / ".local" / "share" / "gamecenter"


APP_DIR = Path(__file__).resolve().parent
UI_DIR = resource_dir() / "ui"
DATA_DIR = default_data_dir()
DAYS_DIR = DATA_DIR / "days"
STATE_FILE = DATA_DIR / "running.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
LOCK = threading.RLock()

J_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
            "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
J_WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"

DEFAULT_SETTINGS = {
    "shop_name": "گیم سنتر",
    "rates": {"1": 80000, "2": 100000, "3": 120000, "4": 140000},
    "rounding": 5,          # دقیقه — گام محاسبه
    "round_mode": "up",     # up | nearest | exact
    "min_minutes": 0,       # حداقل زمان محاسبه
    "drinks": [
        {"name": "نوشابه قوطی", "price": 25000},
        {"name": "نوشابه خانواده", "price": 45000},
        {"name": "دلستر", "price": 30000},
        {"name": "آب معدنی", "price": 10000},
        {"name": "آبمیوه", "price": 35000},
        {"name": "چای", "price": 15000},
        {"name": "قهوه", "price": 40000},
        {"name": "انرژی‌زا", "price": 55000},
        {"name": "چیپس", "price": 20000},
        {"name": "پفک", "price": 15000},
        {"name": "شکلات", "price": 15000},
        {"name": "بستنی", "price": 30000},
    ],
}


# ---------------------------------------------------------------- helpers
def fa(s) -> str:
    return "".join(FA_DIGITS[int(c)] if c.isdigit() else c for c in str(s))


def now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def iso(d: dt.datetime) -> str:
    return d.isoformat(timespec="seconds")


def parse_iso(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if d.tzinfo is not None:
        d = d.astimezone().replace(tzinfo=None)
    return d


def ms(d: dt.datetime) -> int:
    return int(round(d.timestamp() * 1000))


def from_ms(value: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(value / 1000.0)


def now_ms() -> int:
    return int(time.time() * 1000)


def load_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def g2j(gy: int, gm: int, gd: int):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy, gy = 979, gy - 1600
    else:
        jy, gy = 0, gy - 621
    gy2 = gy + 1 if gm > 2 else gy
    days = ((365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100)
            + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1])
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def jalali_parts(d: dt.date):
    jy, jm, jd = g2j(d.year, d.month, d.day)
    return jy, jm, jd


def jalali_date(d: dt.date) -> str:
    """۱۷ آبان ۱۴۰۵"""
    jy, jm, jd = jalali_parts(d)
    return f"{fa(jd)} {J_MONTHS[jm - 1]} {fa(jy)}"


def jalali_full(d: dt.date) -> str:
    """یکشنبه ۱۷ آبان ۱۴۰۵"""
    return f"{J_WEEKDAYS[(d.weekday() + 2) % 7]} {jalali_date(d)}"


def jalali_short(d: dt.date) -> str:
    jy, jm, jd = jalali_parts(d)
    return f"{fa(f'{jy:04d}')}/{fa(f'{jm:02d}')}/{fa(f'{jd:02d}')}"


# ---------------------------------------------------------------- settings
def get_settings() -> dict:
    s = load_json(SETTINGS_FILE, {})
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    if isinstance(s, dict):
        for k, v in s.items():
            if k == "rates" and isinstance(v, dict):
                for hk in ("1", "2", "3", "4"):
                    if hk in v:
                        merged["rates"][hk] = max(0, num(v[hk], merged["rates"][hk]))
            elif k == "drinks" and isinstance(v, list):
                clean = []
                for item in v:
                    if isinstance(item, dict) and str(item.get("name", "")).strip():
                        price = max(0, num(item.get("price", 0)))
                        clean.append({"name": str(item["name"]).strip(), "price": price})
                merged["drinks"] = clean
            elif k in ("rounding", "min_minutes"):
                merged[k] = max(0, num(v, merged[k]))
            elif k == "round_mode" and v in ("up", "nearest", "exact"):
                merged[k] = v
            elif k == "shop_name" and str(v).strip():
                merged["shop_name"] = str(v).strip()
    return merged


# ---------------------------------------------------------------- day book
def new_day(d: dt.date | None = None) -> dict:
    d = d or now().date()
    return {"business_date": d.isoformat(), "opened_at": iso(now()), "sessions": []}


def current_day() -> dict:
    path = DAYS_DIR / "current.json"
    day = load_json(path, None)
    if not isinstance(day, dict) or "sessions" not in day:
        day = new_day()
        save_json(path, day)
    return day


def save_day(day: dict) -> None:
    save_json(DAYS_DIR / "current.json", day)


def load_state() -> dict:
    st = load_json(STATE_FILE, {})
    return st if isinstance(st, dict) else {}


def save_state(st: dict) -> None:
    save_json(STATE_FILE, st)


def public_state(with_settings=True) -> dict:
    settings = get_settings()
    day = current_day()
    st = load_state()
    running = {}
    for console, r in st.items():
        if not isinstance(r, dict) or not r.get("start"):
            continue
        start = parse_iso(r["start"])
        running[str(console)] = {
            "console": str(console),
            "handles": int(r.get("handles", 1)),
            "rate": int(r.get("rate", 0)),
            "start": r.get("start"),
            "start_ms": int(r.get("start_ms") or ms(start)),
            "start_label": fa(start.strftime("%H:%M")),
            "note": r.get("note", ""),
        }
    d = dt.date.fromisoformat(day["business_date"])
    out = {
        "settings": settings if with_settings else {},
        "today": {
            "business_date": day["business_date"],
            "jalali": jalali_short(d),
            "jalali_long": jalali_full(d),
            "opened_at": day.get("opened_at"),
            "sessions": day.get("sessions", []),
            "totals": day_totals(day),
        },
        "running": running,
        "server_time": iso(now()),
        "server_ms": now_ms(),
        "is_stale": d != now().date(),
        "data_dir": str(DATA_DIR),
    }
    return out


# ---------------------------------------------------------------- operations
def op_start(console: str, handles: int, note: str = "") -> dict:
    day = current_day()
    st = load_state()
    if str(console) in st:
        raise ValueError("این دستگاه همین حالا در حال بازی است.")
    handles = max(1, min(4, num(handles, 1) or 1))
    started = now()
    st[str(console)] = {
        "console": str(console),
        "handles": handles,
        "rate": rate_for(handles, get_settings()),
        "start": iso(started),
        "start_ms": ms(started),
        "note": (note or "").strip(),
    }
    save_state(st)
    day.setdefault("meta", {})["last_activity"] = iso(now())
    save_day(day)
    return public_state()


def resolve_end_ms(value, start_ms: int) -> int:
    """The client's clock wins (it is the one the cashier read), clamped so a
    bogus value can never bill the future or a negative duration."""
    srv = now_ms()
    try:
        want = int(round(float(value)))
    except (TypeError, ValueError):
        want = srv
    return max(start_ms, min(want, srv + 2000))


def op_stop(console: str, items, note: str = "", end_ms=None, op_id: str = "") -> dict:
    day = current_day()
    st = load_state()

    # a retried settle must never bill the same session twice
    if op_id:
        for s in day.get("sessions", []):
            if s.get("op_id") == op_id:
                return {"session": s, "state": public_state(), "duplicate": True}

    r = st.pop(str(console), None)
    if not r:
        raise ValueError("این دستگاه در حال بازی نیست.")

    start_ms = int(r.get("start_ms") or ms(parse_iso(r["start"])))
    end = resolve_end_ms(end_ms, start_ms)
    settings = get_settings()
    rate = int(r.get("rate") or rate_for(r.get("handles", 1), settings))
    b = bill((end - start_ms) / 1000.0, rate, settings)

    clean = normalise_items(items)
    items_sum = sum(i["price"] * i["qty"] for i in clean)
    entry = {
        "id": secrets.token_hex(6),
        "op_id": str(op_id or "")[:64],
        "console": str(console),
        "handles": int(r.get("handles", 1)),
        "rate": rate,
        "start": iso(from_ms(start_ms)),
        "end": iso(from_ms(end)),
        "start_ms": start_ms,
        "end_ms": end,
        "seconds": round_half_up(b["seconds"]),
        "minutes": b["minutes"],
        "play": b["play"],
        "items": clean,
        "items_total": items_sum,
        "total": b["play"] + items_sum,
        "note": (note or r.get("note") or "").strip()[:120],
        "manual": False,
        "at": iso(now()),
    }
    day.setdefault("sessions", []).append(entry)
    save_day(day)
    save_state(st)
    return {"session": entry, "state": public_state()}


def op_cancel(console: str) -> dict:
    st = load_state()
    if str(console) not in st:
        raise ValueError("این دستگاه در حال بازی نیست.")
    st.pop(str(console))
    save_state(st)
    return public_state()


def op_manual(payload: dict) -> dict:
    day = current_day()
    handles = max(1, min(4, num(payload.get("handles", 1), 1) or 1))
    try:
        start = parse_iso(str(payload["start"]))
        end = parse_iso(str(payload["end"]))
    except Exception:
        raise ValueError("زمان شروع یا پایان نامعتبر است.")
    if end < start:
        raise ValueError("زمان پایان نمی‌تواند قبل از شروع باشد.")
    start_ms, end_ms = ms(start), ms(end)
    if end_ms > now_ms() + 60_000:
        raise ValueError("زمان پایان نمی‌تواند در آینده باشد.")
    if (end_ms - start_ms) / 1000.0 > MAX_SESSION_SECONDS:
        raise ValueError("مدت بازی نمی‌تواند بیش از ۲۴ ساعت باشد.")

    settings = get_settings()
    rate = rate_for(handles, settings)
    b = bill((end_ms - start_ms) / 1000.0, rate, settings)
    extra = max(0, num(payload.get("extra", 0)))
    items = []
    if extra:
        items.append({"name": str(payload.get("extra_name") or "متفرقه").strip()[:60], "price": extra, "qty": 1})
    entry = {
        "id": secrets.token_hex(6),
        "op_id": str(payload.get("op_id") or "")[:64],
        "console": str(payload.get("console", "1")),
        "handles": handles,
        "rate": rate,
        "start": iso(from_ms(start_ms)),
        "end": iso(from_ms(end_ms)),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "seconds": round_half_up(b["seconds"]),
        "minutes": b["minutes"],
        "play": b["play"],
        "items": items,
        "items_total": extra,
        "total": b["play"] + extra,
        "note": str(payload.get("note", "")).strip()[:120],
        "manual": True,
        "at": iso(now()),
    }
    day.setdefault("sessions", []).append(entry)
    save_day(day)
    return public_state()


def op_delete(entry_id: str) -> dict:
    day = current_day()
    before = len(day.get("sessions", []))
    day["sessions"] = [s for s in day.get("sessions", []) if s.get("id") != entry_id]
    if len(day["sessions"]) == before:
        raise ValueError("این ردیف پیدا نشد.")
    save_day(day)
    return public_state()


def op_update_settings(payload: dict) -> dict:
    cur = get_settings()
    shop = str(payload.get("shop_name", cur["shop_name"])).strip()[:40] or cur["shop_name"]
    rates = {}
    incoming = payload.get("rates") or {}
    for h in ("1", "2", "3", "4"):
        rates[h] = max(0, num(incoming.get(h, cur["rates"][h]), cur["rates"][h]))
    rounding = max(0, num(payload.get("rounding", cur["rounding"]), cur["rounding"]))
    min_minutes = max(0, num(payload.get("min_minutes", cur["min_minutes"]), cur["min_minutes"]))
    mode = payload.get("round_mode", cur["round_mode"])
    if mode not in ("up", "nearest", "exact"):
        mode = cur["round_mode"]
    drinks = normalise_items([dict(d, qty=1) for d in payload.get("drinks", cur["drinks"])])
    new = {"shop_name": shop, "rates": rates, "rounding": rounding,
           "round_mode": mode, "min_minutes": min_minutes,
           "drinks": [{"name": d["name"], "price": d["price"]} for d in drinks]}
    save_json(SETTINGS_FILE, new)
    return public_state()


def op_close_day() -> dict:
    day = current_day()
    st = load_state()
    if st:
        raise ValueError("تا وقتی دستگاه فعال است نمی‌توان روز را بست.")
    if not day.get("sessions"):
        raise ValueError("امروز هیچ حسابی ثبت نشده است.")
    d = dt.date.fromisoformat(day["business_date"])
    stamp = now().strftime("%Y-%m-%d_%H%M%S")
    name = f"{day['business_date']}_{stamp}.json"
    n = 2
    while (DAYS_DIR / name).exists():  # never overwrite an archived day
        name = f"{day['business_date']}_{stamp}-{n}.json"
        n += 1
    totals = day_totals(day)
    day["closed_at"] = iso(now())
    day["totals"] = totals
    save_json(DAYS_DIR / name, day)
    save_json(DAYS_DIR / "current.json", new_day())
    return {"file": name, "summary": {
        "business_date": day["business_date"],
        "jalali": jalali_date(d),
        "jalali_long": jalali_full(d),
        "closed_at": day["closed_at"],
        **totals,
    }, "state": public_state()}


def list_archived_days() -> list:
    out = []
    for p in sorted(DAYS_DIR.glob("*.json"), reverse=True):
        if p.name == "current.json":
            continue
        day = load_json(p, None)
        if not isinstance(day, dict) or "sessions" not in day:
            continue
        try:
            d = dt.date.fromisoformat(day["business_date"])
        except Exception:
            d = now().date()
        t = day_totals(day)
        out.append({
            "file": p.name,
            "business_date": day.get("business_date"),
            "jalali": jalali_short(d),
            "jalali_long": jalali_full(d),
            "closed_at": day.get("closed_at") or "",
            "closed_time": fa(parse_iso(day["closed_at"]).strftime("%H:%M")) if day.get("closed_at") else "—",
            **t,
        })
    return out


def day_json(file: str) -> dict:
    safe = Path(file).name
    day = load_json(DAYS_DIR / safe, None)
    if not isinstance(day, dict) or "sessions" not in day:
        raise ValueError("روز مورد نظر پیدا نشد.")
    d = dt.date.fromisoformat(day.get("business_date") or now().date().isoformat())
    day["jalali_long"] = jalali_full(d)
    day["jalali"] = jalali_short(d)
    day["totals"] = day_totals(day)
    return day


def day_csv(file: str | None = None) -> bytes:
    if file:
        day = day_json(file)
        title = jalali_full(dt.date.fromisoformat(day["business_date"]))
    else:
        day = current_day()
        title = jalali_full(dt.date.fromisoformat(day["business_date"]))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["تاریخ", title])
    w.writerow([])
    w.writerow(["دستگاه", "دسته", "شروع", "پایان", "مدت (دقیقه)",
                "نرخ ساعتی", "هزینه بازی", "نوشیدنی", "جمع", "توضیح"])
    for s in day.get("sessions", []):
        w.writerow([
            s.get("console"), s.get("handles"),
            parse_iso(s["start"]).strftime("%H:%M"),
            parse_iso(s["end"]).strftime("%H:%M"),
            s.get("minutes"), s.get("rate"), s.get("play"),
            s.get("items_total"), s.get("total"),
            "، ".join(f"{i['name']}×{i['qty']}" for i in s.get("items", [])) or "",
        ])
    t = day_totals(day)
    w.writerow([])
    w.writerow(["جمع بازی", t["play"]])
    w.writerow(["جمع نوشیدنی", t["items"]])
    w.writerow(["جمع کل", t["total"]])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "GameCenter/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # --- plumbing
    def _send(self, code=200, body=b"", ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _err(self, msg, code=400):
        self._json({"ok": False, "error": msg}, code)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _static(self, rel: str):
        root = UI_DIR.resolve()
        p = (root / rel).resolve()
        if root not in p.parents or not p.is_file():
            self._err("not found", 404)
            return
        ctype = {".html": "text/html; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8",
                 ".svg": "image/svg+xml"}.get(p.suffix, "application/octet-stream")
        self._send(200, p.read_bytes(), ctype)

    # --- routes
    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        try:
            with LOCK:
                if path in ("/", "/index.html"):
                    return self._static("index.html")
                if path == "/api/ping":
                    return self._json({"ok": True})
                if path == "/api/state":
                    return self._json({"ok": True, **public_state()})
                if path == "/api/days":
                    return self._json({"ok": True, "days": list_archived_days()})
                if path == "/api/day":
                    return self._json({"ok": True, "day": day_json(q.get("f", [""])[0])})
                if path == "/api/export.csv":
                    f = q.get("f", [None])[0] or None
                    day = day_json(f) if f else current_day()
                    d = dt.date.fromisoformat(day["business_date"])
                    name = f"gamecenter-{d.isoformat()}.csv"
                    return self._send(200, day_csv(f),
                                      "text/csv; charset=utf-8",
                                      {"Content-Disposition": f'attachment; filename="{name}"'})
                return self._static(path.lstrip("/"))
        except ValueError as e:
            return self._err(str(e))
        except Exception as e:  # noqa: BLE001
            return self._err(f"خطای سرور: {e}", 500)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        data = self._body()
        try:
            with LOCK:
                if path == "/api/start":
                    return self._json({"ok": True, **op_start(
                        str(data.get("console", "1")), data.get("handles", 1), data.get("note", ""))})
                if path == "/api/stop":
                    return self._json({"ok": True, **op_stop(
                        str(data.get("console", "1")), data.get("items", []), data.get("note", ""),
                        data.get("end_ms"), data.get("op_id", ""))})
                if path == "/api/cancel":
                    return self._json({"ok": True, "state": op_cancel(str(data.get("console", "1")))})
                if path == "/api/manual":
                    return self._json({"ok": True, "state": op_manual(data)})
                if path == "/api/delete":
                    return self._json({"ok": True, "state": op_delete(str(data.get("id", "")))})
                if path == "/api/settings":
                    return self._json({"ok": True, "state": op_update_settings(data)})
                if path == "/api/close-day":
                    return self._json({"ok": True, **op_close_day()})
                return self._err("مسیر نامعتبر", 404)
        except ValueError as e:
            return self._err(str(e))
        except Exception as e:  # noqa: BLE001
            return self._err(f"خطای سرور: {e}", 500)


def log(msg: str) -> None:
    """A windowed .exe has no console — keep a log file instead."""
    try:
        if sys.stdout is not None:
            print(msg, flush=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with (DATA_DIR / "server.log").open("a", encoding="utf-8") as f:
            f.write(f"{iso(now())} {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def server_up(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/ping", timeout=0.6) as r:
            return json.loads(r.read().decode("utf-8")).get("ok") is True
    except Exception:  # noqa: BLE001
        return False


def find_browser() -> str | None:
    """A Chromium-family browser gives us a chrome-less app window."""
    names = ["chrome", "msedge", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]
    paths = [shutil.which(n) for n in names]
    if os.name == "nt":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if not base:
                continue
            paths.append(str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))
            paths.append(str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    for p in paths:
        if p and Path(p).is_file():
            return p
    return None


def open_ui(url: str) -> None:
    exe = find_browser()
    if exe:
        try:
            subprocess.Popen(
                [exe, f"--app={url}", f"--user-data-dir={DATA_DIR / 'browser-profile'}",
                 "--window-size=1560,980", "--no-first-run", "--no-default-browser-check",
                 "--disable-features=Translate,MediaRouter", "--lang=fa"],
                close_fds=True,
                # a windowed .exe has no valid std handles to inherit
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
        except OSError:
            pass
    webbrowser.open(url)


def main():
    ap = argparse.ArgumentParser(description="GameCenter — local day book")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--stop", action="store_true", help="stop the running instance")
    ap.add_argument("--open", dest="open_ui", action="store_true", default=FROZEN,
                    help="open the UI in a browser window once the server is up")
    ap.add_argument("--no-open", dest="open_ui", action="store_false")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DAYS_DIR.mkdir(parents=True, exist_ok=True)
    pidfile = DATA_DIR / "server.pid"
    url = f"http://{args.host}:{args.port}"

    if args.stop:
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 15)
            pidfile.unlink(missing_ok=True)
            log(f"stopped {pid}")
        except Exception as e:  # noqa: BLE001
            log(f"not running: {e}")
        return

    # double-clicked twice? just show the window that is already running.
    if server_up(args.host, args.port):
        log(f"GameCenter already running on {url}")
        if args.open_ui:
            open_ui(url)
        return

    if not SETTINGS_FILE.exists():
        save_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    current_day()  # make sure a book exists

    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        log(f"cannot listen on {url}: {e}")
        if args.open_ui:
            open_ui(url)
        return 1
    httpd.daemon_threads = True
    pidfile.write_text(str(os.getpid()))
    log(f"GameCenter ready on {url}  →  {DATA_DIR}")

    if args.open_ui:
        threading.Thread(target=lambda: (time.sleep(0.3), open_ui(url)), daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        pidfile.unlink(missing_ok=True)
        httpd.server_close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except Exception:  # noqa: BLE001
        import traceback
        log("fatal: " + traceback.format_exc())
        raise
