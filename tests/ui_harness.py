#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
گیم سنتر — UI/UX harness
Runs the real app (isolated data dir) in Chromium via Playwright and checks
the flows, the billing math, console errors and layout overflow.

    python3 tests/ui_harness.py            # headless, all checks
    python3 tests/ui_harness.py --headed   # watch it happen
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("GC_TEST_PORT", "8899"))
BASE = f"http://127.0.0.1:{PORT}"
DATA = pathlib.Path("/tmp/gc-test-data")
SHOTS = pathlib.Path("/tmp/gc-shots")
CHROME = "/usr/bin/chromium"

FA = "۰۱۲۳۴۵۶۷۸۹"
RESULT: list[tuple[bool, str, str]] = []


def fa(s) -> str:
    return "".join(FA[int(c)] if c.isdigit() else c for c in str(s))


def money(n) -> str:
    n = int(round(float(n)))
    return fa(f"{n:,}".replace(",", "٬"))


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULT.append((bool(ok), name, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    return ok


def eq(name: str, got, want) -> bool:
    return check(name, got == want, f"got {got!r} want {want!r}")


def api(path: str):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return json.load(r)


def post_json(path: str, body: dict):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def wait_server(timeout: float = 15) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(BASE + "/api/ping", timeout=1) as r:
                if json.load(r).get("ok"):
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(.15)
    return False


class App:
    def __init__(self, page: Page):
        self.p = page
        self.errors: list[str] = []
        self.posts: list[tuple[str, dict]] = []
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("console", self._console)
        page.on("requestfailed", lambda r: self.errors.append(f"requestfailed: {r.url}"))
        page.on("request", self._request)

    def _request(self, req):
        if "/api/stop" in req.url and req.method == "POST":
            try:
                self.posts.append((req.url, json.loads(req.post_data or "{}")))
            except ValueError:
                pass

    def last_stop(self) -> dict:
        return self.posts[-1][1] if self.posts else {}

    def _console(self, msg):
        if msg.type in ("error",):
            self.errors.append(f"console: {msg.text}")

    # helpers -------------------------------------------------------
    def state(self):
        return self.p.evaluate("JSON.parse(JSON.stringify(S))")

    def card(self, c):
        return self.p.locator(f'.card[data-c="{c}"]')

    def money_text(self, sel) -> str:
        return self.p.locator(sel).inner_text().strip()

    def shot(self, name: str):
        SHOTS.mkdir(parents=True, exist_ok=True)
        self.p.screenshot(path=str(SHOTS / f"{name}.png"))


def run(headed: bool) -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    if DATA.exists():
        shutil.rmtree(DATA)
    env = dict(os.environ, GAMECENTER_DATA=str(DATA))
    srv = subprocess.Popen([sys.executable, str(ROOT / "app.py"), "--port", str(PORT)],
                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_server():
            print("server did not start")
            return 1

        with sync_playwright() as pw:
            browser: Browser = pw.chromium.launch(executable_path=CHROME, headless=not headed,
                                                  args=["--force-device-scale-factor=1"])
            ctx = browser.new_context(viewport={"width": 1560, "height": 980}, locale="fa-IR")
            page = ctx.new_page()
            app = App(page)
            page.goto(BASE, wait_until="load")
            page.wait_for_timeout(900)

            # ── 1. boot ───────────────────────────────────────────
            eq("boot: 4 console cards", page.locator(".card").count(), 4)
            check("boot: empty state visible", page.locator("#logEmpty").is_visible())
            eq("boot: no sessions", len(app.state()["today"]["sessions"]), 0)
            check("boot: GSAP loaded", page.evaluate("!!window.gsap"))
            check("boot: settings present in state", bool(app.state()["settings"].get("rates")))
            app.shot("01-boot")

            # ── 2. start a session from the UI ────────────────────
            c1 = app.card(1)
            c1.locator('.handles button[data-h="2"]').click()
            page.wait_for_timeout(250)
            eq("start: free card shows rate for 2 handles", c1.locator(".price-row .money").inner_text().strip(), money(100000))
            c1.locator(".start-btn").click()
            page.wait_for_timeout(1600)
            check("start: card went busy", "busy" in (c1.get_attribute("class") or ""))
            st = app.state()
            check("start: session running", "1" in st["running"], str(st["running"]))
            eq("start: handles recorded", st["running"]["1"]["handles"], 2)
            eq("start: rate snapshot", st["running"]["1"]["rate"], 100000)
            timer_txt = c1.locator(".timer").inner_text().strip()
            check("start: timer ticking", timer_txt not in ("۰۰:۰۰:۰۰", ""), timer_txt)
            check("start: live cost shown", c1.locator("[data-cost]").inner_text().strip() != "۰",
                  c1.locator("[data-cost]").inner_text().strip())
            live = page.evaluate("""() => {
              const run = S.running['1'];
              const b = GCBilling.bill(runSeconds(run), run.rate, S.settings);
              return { play: b.play, minutes: b.minutes,
                       shown: document.querySelector('.card[data-c="1"] [data-cost]').textContent,
                       want: fmtMoney(b.play) };
            }""")
            eq("live: card shows the shared formula's number", live["shown"], live["want"])
            eq("live: one second of play bills the 5-minute step", live["play"], 8333)
            eq("live: billed minutes follow the rounding rule", live["minutes"], 5)
            check("live: start_ms is a real clock stamp",
                  isinstance(st["running"]["1"].get("start_ms"), int), str(st["running"]["1"]))
            check("start: step bar has width", c1.locator("[data-step]").evaluate("e => e.style.width") != "")
            check("regression: settings not wiped by start", bool(app.state()["settings"].get("rates")))
            app.shot("02-running")

            # ── 3. handle switch on a free card updates the rate ──
            c2 = app.card(2)
            c2.locator('.handles button[data-h="4"]').click()
            page.wait_for_timeout(250)
            eq("handles: rate follows 4 handles", c2.locator(".price-row .money").inner_text().strip(), money(140000))
            eq("handles: label follows selection", c2.locator(".meta-row").inner_text().split("نرخ")[-1].strip(),
               "۴ دسته")

            # ── 4. settle with drinks ─────────────────────────────
            c1.locator(".stop-btn").click()
            page.wait_for_timeout(500)
            check("settle: modal visible", page.locator("#overlay").is_visible())
            page.locator("#drinkPick .drink-btn").nth(0).click()
            page.locator("#drinkPick .drink-btn").nth(0).click()
            page.locator("#drinkPick .drink-btn").nth(2).click()
            page.wait_for_timeout(200)
            eq("settle: bill lines", page.locator("#billList li").count(), 2)
            page.fill("#customName", "پیتزا")
            page.fill("#customPrice", "120000")
            page.click("#customAdd")
            page.wait_for_timeout(250)
            eq("settle: bill lines after custom item", page.locator("#billList li").count(), 3)

            rates = app.state()["settings"]["rates"]
            drinks = app.state()["settings"]["drinks"]
            expect_items = drinks[0]["price"] * 2 + drinks[2]["price"] * 1 + 120000
            shown_total = page.locator("#mGrand").inner_text()
            # play cost is time dependent; only sanity-check the item part
            bills = page.locator("#mTotals .row .money").all_inner_texts()
            check("settle: drink subtotal correct", bills[1].replace(" تومان", "") == money(expect_items),
                  f"{bills[1]} vs {money(expect_items)}")
            modal_play = page.evaluate("""() => {
              const run = S.running['1'];
              const b = GCBilling.bill(runSeconds(run), run.rate, S.settings);
              return { want: fmtMoney(b.play), shown: document.querySelectorAll('#mTotals .row .money')[0].textContent };
            }""")
            check("settle: play line is the shared formula's number",
                  modal_play["shown"].replace(" تومان", "").strip() == modal_play["want"],
                  json.dumps(modal_play, ensure_ascii=False))
            shown_total = int(page.get_attribute("#mTotals", "data-total") or 0)
            app.shot("03-settle")
            page.click("#mConfirm")
            page.wait_for_timeout(900)
            check("settle: modal closed", not page.locator("#overlay").is_visible())
            st = app.state()
            eq("settle: session stored", len(st["today"]["sessions"]), 1)
            eq("settle: console freed", len(st["running"]), 0)
            row = st["today"]["sessions"][0]
            eq("settle: items_total", row["items_total"], expect_items)
            check("settle: row total = play + items", row["total"] == row["play"] + row["items_total"], str(row))
            posted = app.last_stop()
            eq("settle: server billed the exact instant the UI froze", row["end_ms"], posted.get("end_ms"))
            eq("settle: op id travelled with the request", row.get("op_id"), posted.get("op_id"))
            recomputed = page.evaluate("""(row) => GCBilling.bill((row.end_ms - row.start_ms) / 1000,
                                        row.rate, S.settings).play""", row)
            eq("settle: recorded play recomputes from the stored timestamps", row["play"], recomputed)
            step_money = row["rate"] * app.state()["settings"]["rounding"] / 60
            check("settle: screen total is within one billing step of the book",
                  abs(row["total"] - shown_total) <= step_money,
                  f"screen {shown_total} book {row['total']} step {step_money}")
            eq("settle: table rows", page.locator("#logBody tr").count(), 1)
            eq("settle: footer total matches", page.get_attribute("#footTotal", "data-val"), str(row["total"]))
            app.shot("04-after-settle")

            # ── 5. delete with the styled confirm ─────────────────
            page.locator("#logBody tr .row-del").first.click()
            page.wait_for_timeout(400)
            check("delete: styled confirm shown", page.locator("#cfYes").is_visible())
            page.click("#cfNo")
            page.wait_for_timeout(350)
            eq("delete: cancel keeps row", len(app.state()["today"]["sessions"]), 1)
            page.locator("#logBody tr .row-del").first.click()
            page.wait_for_timeout(350)
            page.click("#cfYes")
            page.wait_for_timeout(800)
            eq("delete: row removed", len(app.state()["today"]["sessions"]), 0)
            eq("delete: empty state back", page.locator("#logEmpty").is_visible(), True)

            # ── 6. cancel a running session ───────────────────────
            c3 = app.card(3)
            c3.locator(".start-btn").click()
            page.wait_for_timeout(900)
            c3.locator(".cancel-btn").click()
            page.wait_for_timeout(400)
            check("cancel: confirm shown", page.locator("#cfYes").is_visible())
            page.click("#cfYes")
            page.wait_for_timeout(800)
            eq("cancel: console freed", len(app.state()["running"]), 0)
            eq("cancel: nothing recorded", len(app.state()["today"]["sessions"]), 0)

            # ── 7. manual entry ───────────────────────────────────
            page.click("#btnManual")
            page.wait_for_timeout(500)
            start = (dt.datetime.now() - dt.timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M")
            end = dt.datetime.now().strftime("%Y-%m-%dT%H:%M")
            page.fill("#mnStart", start)
            page.fill("#mnEnd", end)
            page.select_option("#mnHandles", "3")
            page.fill("#mnExtra", "45000")
            page.fill("#mnExtraName", "هله‌هوله")
            page.wait_for_timeout(250)
            app.shot("05-manual")
            page.click("#mnSave")
            page.wait_for_timeout(900)
            rows = app.state()["today"]["sessions"]
            eq("manual: row added", len(rows), 1)
            eq("manual: handles", rows[0]["handles"], 3)
            eq("manual: minutes billed (90m → 90)", rows[0]["minutes"], 90)
            eq("manual: play cost", rows[0]["play"], 180000)  # 120000/h × 1.5h
            eq("manual: extra as item", rows[0]["items_total"], 45000)

            # ── 8. settings round-trip ────────────────────────────
            app.card(1).locator('.handles button[data-h="1"]').click()
            page.wait_for_timeout(250)
            page.click("#btnSettings")
            page.wait_for_timeout(500)
            page.fill("#stRate1", "95000")
            page.fill("#stName", "گیم سنتر تست")
            page.click("#drinkAdd")
            page.wait_for_timeout(200)
            rows_edit = page.locator("#drinkEdit .de-row")
            n = rows_edit.count()
            rows_edit.nth(n - 1).locator(".de-name").fill("نوشابه تست")
            rows_edit.nth(n - 1).locator(".de-price").fill("12000")
            app.shot("06-settings")
            page.click("#stSave")
            page.wait_for_timeout(900)
            st = app.state()["settings"]
            eq("settings: rate saved", st["rates"]["1"], 95000)
            eq("settings: shop name saved", st["shop_name"], "گیم سنتر تست")
            eq("settings: drink appended", st["drinks"][-1]["name"], "نوشابه تست")
            eq("settings: header reflects name", page.locator("#shopName").inner_text().strip(), "گیم سنتر تست")
            eq("settings: free card rate updated", app.card(1).locator(".price-row .money").inner_text().strip(), money(95000))

            # ── 9. keyboard shortcuts ─────────────────────────────
            page.locator("body").click(position={"x": 5, "y": 5})
            page.keyboard.press("2")
            page.wait_for_timeout(900)
            check("keys: '2' starts console 2", "2" in app.state()["running"])
            page.keyboard.press("2")
            page.wait_for_timeout(500)
            check("keys: '2' opens settle modal", page.locator("#overlay").is_visible())
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            check("keys: Escape closes modal", not page.locator("#overlay").is_visible())
            page.click('.card[data-c="2"] .cancel-btn')
            page.wait_for_timeout(350)
            page.click("#cfYes")
            page.wait_for_timeout(700)

            # ── 10. print sheet ───────────────────────────────────
            page.evaluate("window.print = () => { window.__printed = document.getElementById('printArea').innerHTML; }")
            page.click("#btnPrint")
            page.wait_for_timeout(500)
            printed = page.evaluate("window.__printed || ''")
            check("print: sheet generated", "حساب روزانه" in printed and "دستگاه" in printed, printed[:80])
            check("print: totals row present", "جمع کل" in printed)

            # ── 11. CSV + archive + close day ─────────────────────
            resp = page.request.get(BASE + "/api/export.csv")
            body = resp.body().decode("utf-8-sig")
            check("csv: BOM + header", body.startswith("تاریخ") and "هزینه بازی" in body, body[:40])
            check("csv: has the manual row", "180000" in body)

            page.click("#btnCloseDay")
            page.wait_for_timeout(500)
            check("close-day: summary modal", page.locator("#cdOk").is_visible())
            app.shot("07-close-day")
            page.click("#cdOk")
            page.wait_for_timeout(1100)
            page.click("#ok")
            page.wait_for_timeout(600)
            eq("close-day: book reset", len(app.state()["today"]["sessions"]), 0)
            check("close-day: archive file written", len(list((DATA / "days").glob("*.json"))) >= 2)

            page.click("#btnArchive")
            page.wait_for_timeout(700)
            eq("archive: one day listed", page.locator("table.arc tbody tr").count(), 1)
            app.shot("08-archive")
            page.locator("table.arc tbody tr").first.click()
            page.wait_for_timeout(700)
            check("archive: day detail opens", page.locator(".modal-head h3").inner_text().startswith("حساب"))
            check("archive: detail has rows", page.locator("#modalBody tbody tr").count() >= 1)
            page.evaluate("window.print = () => { window.__printed2 = 1; }")
            page.click("#dPrint")
            page.wait_for_timeout(400)
            sheet = page.evaluate("document.getElementById('printArea').innerHTML")
            check("archive: print sheet filled", page.evaluate("window.__printed2 === 1") and money(225000) in sheet,
                  sheet[:120])
            app.shot("09-archive-detail")
            page.click("#modalClose")
            page.wait_for_timeout(400)

            # ── 12. layout: no overflow at 4 sizes ────────────────
            for w, h in ((1560, 980), (1366, 768), (1280, 800), (1024, 700)):
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(450)
                over = page.evaluate("""() => {
                  const d = document.documentElement;
                  let worst = 0, who = '';
                  document.querySelectorAll('.card,.panel,.topbar,.stat,.actions,.log-foot').forEach(el => {
                    const r = el.getBoundingClientRect();
                    const ov = Math.max(r.right - d.clientWidth, r.bottom - d.clientHeight, -r.left, -r.top);
                    if (ov > worst) { worst = ov; who = el.className; }
                  });
                  return { scrollW: d.scrollWidth, clientW: d.clientWidth,
                           scrollH: d.scrollHeight, clientH: d.clientHeight, worst, who };
                }""")
                ok = over["scrollW"] <= over["clientW"] + 1 and over["scrollH"] <= over["clientH"] + 1 and over["worst"] <= 1
                check(f"layout {w}x{h}: no overflow", ok, json.dumps(over, ensure_ascii=False))
                app.shot(f"10-layout-{w}x{h}")
            page.set_viewport_size({"width": 1560, "height": 980})
            page.wait_for_timeout(300)

            # ── 13. reduced motion ────────────────────────────────
            ctx2 = browser.new_context(viewport={"width": 1400, "height": 900}, reduced_motion="reduce")
            p2 = ctx2.new_page()
            app2 = App(p2)
            p2.goto(BASE, wait_until="load")
            p2.wait_for_timeout(700)
            eq("reduced-motion: cards render", p2.locator(".card").count(), 4)
            check("reduced-motion: no console errors", not app2.errors, "; ".join(app2.errors[:2]))
            check("reduced-motion: no tilt transform", "matrix" not in (p2.locator('.card[data-c="1"]').evaluate("e => getComputedStyle(e).transform") or ""))
            p2.close()
            ctx2.close()

            # ── 14. stale-day banner ──────────────────────────────
            dayf = DATA / "days" / "current.json"
            d = json.loads(dayf.read_text())
            d["business_date"] = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            d["sessions"] = []
            dayf.write_text(json.dumps(d, ensure_ascii=False))
            page.reload(wait_until="load")
            page.wait_for_timeout(900)
            check("stale: banner appears", page.locator("#staleBar").is_visible())
            app.shot("11-stale")

            # ── 15. nearest rounding is half-up everywhere ────────
            st = app.state()["settings"]
            post_json("/api/settings", {**st, "rounding": 15, "round_mode": "nearest"})
            page.reload(wait_until="load")
            page.wait_for_timeout(700)
            nowd = dt.datetime.now()
            r = post_json("/api/manual", {
                "console": "4", "handles": 1,
                "start": (nowd - dt.timedelta(minutes=22, seconds=30)).isoformat(timespec="seconds"),
                "end": nowd.isoformat(timespec="seconds"),
                "extra": 0, "extra_name": "", "note": "تست گرد کردن",
            })
            mrow = r["state"]["today"]["sessions"][-1]
            eq("rounding: 22.5 min on a 15-minute nearest grid bills 30", mrow["minutes"], 30)
            eq("rounding: play follows the billed minutes", mrow["play"], round(st["rates"]["1"] * 30 / 60))
            js = page.evaluate("""() => GCBilling.bill(22.5 * 60, 95000,
                                    {rounding: 15, round_mode: 'nearest', min_minutes: 0})""")
            eq("rounding: browser agrees with the server", js["minutes"], 30)
            eq("rounding: browser money agrees with the server", js["play"], 47500)
            page.click("#logBody tr:last-child .row-del")
            page.wait_for_timeout(350)
            page.click("#cfYes")
            page.wait_for_timeout(700)

            # ── 16. console errors overall ────────────────────────
            real = [e for e in app.errors if "favicon" not in e and "status of 404" not in e]
            check("no console/page errors", not real, "; ".join(real[:4]))

            browser.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()

    failed = [r for r in RESULT if not r[0]]
    print("\n" + "─" * 62)
    print(f"{len(RESULT) - len(failed)}/{len(RESULT)} checks passed")
    if failed:
        print("\nFAILURES:")
        for _, name, detail in failed:
            print(f"  · {name} — {detail}")
    print(f"screenshots → {SHOTS}")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    sys.exit(run(ap.parse_args().headed))
