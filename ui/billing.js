/* ══════════════════════════════════════════════════════════════════
   گیم سنتر — حساب‌وکتاب (mirror of billing.py)

   Every number the cashier sees must equal the number the server records,
   so both sides use the same formula and the same round-half-up rule:

       cost = rate (per hour) × billed minutes ÷ 60

   tests/test_billing.py runs the same cases through Python and Node.
   ══════════════════════════════════════════════════════════════════ */
(function (root) {
  'use strict';

  const FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
  const AR_DIGITS = '٠١٢٣٤٥٦٧٨٩';

  function toAsciiDigits(str) {
    return String(str)
      .replace(/[۰-۹]/g, (d) => String(FA_DIGITS.indexOf(d)))
      .replace(/[٠-٩]/g, (d) => String(AR_DIGITS.indexOf(d)));
  }

  /* parse like a Persian keyboard would send it: ۱۰۰٬۰۰۰ / 100,000 / 100000 */
  function num(v, def = 0) {
    if (typeof v === 'number') return Number.isFinite(v) ? Math.round(v) : def;
    if (v == null || v === '') return def;
    const digits = toAsciiDigits(v).replace(/[^\d-]/g, '');
    if (digits === '' || digits === '-') return def;
    const n = parseInt(digits, 10);
    return Number.isFinite(n) ? n : def;
  }

  const roundHalfUp = (x) => Math.floor(Number(x) + 0.5);
  const round2 = (x) => Math.round(Number(x) * 100) / 100;

  function billMinutes(sec, st) {
    const raw = Math.max(0, Number(sec) || 0) / 60;
    const step = num(st && st.rounding, 0);
    const mode = (st && st.round_mode) || 'up';
    let m;
    if (step <= 0 || mode === 'exact') m = raw;
    else if (mode === 'nearest') m = Math.floor(raw / step + 0.5) * step;
    else m = Math.ceil(raw / step) * step;
    return Math.max(m, num(st && st.min_minutes, 0));
  }

  /* rate is per hour; minutes is the billed duration */
  function playCost(min, rate) {
    return roundHalfUp((num(rate) * (Number(min) || 0)) / 60);
  }

  /* the one function both the live timer and the receipt use */
  function bill(sec, rate, st) {
    const seconds = Math.max(0, Number(sec) || 0);
    const minutes = round2(billMinutes(seconds, st));
    return { seconds, minutes, play: playCost(minutes, rate) };
  }

  /* bill a session whose rate changed mid-way — mirror of billing.bill_plan.
     legs: [{from_ms, rate, mode?, handles?}...] chronological, last leg open,
     ends at endMs. Each leg is billed with the shop's rounding; the
     minimum-time floor applies once, at the last leg's rate. One leg is
     exactly bill(). */
  function billPlan(legs, st, endMs) {
    const clean = (Array.isArray(legs) ? legs : [])
      .filter((l) => l && num(l.from_ms, -1) >= 0)
      .map((l) => ({ ...l, from_ms: num(l.from_ms, 0), rate: num(l.rate, 0) }));
    if (!clean.length) clean.push({ from_ms: 0, rate: 0 });
    const end = num(endMs, 0);
    const n = clean.length;
    const bounds = (i) => {
      const frm = clean[i].from_ms;
      const raw = i + 1 < n ? clean[i + 1].from_ms : end;
      return [frm, Math.max(frm, Math.min(raw, end))];
    };
    const pick = (l) => ({ mode: l.mode, handles: l.handles });
    const detail = [];
    if (n === 1) {
      const [frm, to] = bounds(0);
      const sec = Math.max(0, (to - frm) / 1000);
      const b = bill(sec, clean[0].rate, st);
      detail.push({ ...pick(clean[0]), rate: clean[0].rate, from_ms: frm, to_ms: to,
        seconds: b.seconds, minutes: b.minutes, play: b.play });
      return { seconds: b.seconds, minutes: b.minutes, play: b.play, legs: detail, min_extra: 0 };
    }
    const nofloor = { ...(st || {}), min_minutes: 0 };
    let totalMin = 0, play = 0, seconds = 0;
    for (let i = 0; i < n; i++) {
      const [frm, to] = bounds(i);
      const sec = Math.max(0, (to - frm) / 1000);
      const minutes = round2(billMinutes(sec, nofloor));
      const p = playCost(minutes, clean[i].rate);
      detail.push({ ...pick(clean[i]), rate: clean[i].rate, from_ms: frm, to_ms: to,
        seconds: sec, minutes, play: p });
      totalMin += minutes; play += p; seconds += sec;
    }
    totalMin = round2(totalMin);
    const deficit = Math.max(0, num(st && st.min_minutes, 0) - totalMin);
    const minPlay = deficit > 0 ? playCost(deficit, clean[n - 1].rate) : 0;
    return { seconds, minutes: round2(totalMin + deficit), play: play + minPlay,
             legs: detail, min_extra: deficit };
  }

  function fa(s) {
    return String(s).replace(/[0-9]/g, (d) => FA_DIGITS[+d]);
  }

  /* 25 → ۲۵ · 24.6 → ۲۴٫۶ */
  function fmtMinutes(m) {
    const v = round2(m);
    const s = Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
    return fa(s.replace('.', '٫'));
  }

  root.GCBilling = { num, roundHalfUp, round2, billMinutes, playCost, bill, billPlan, fmtMinutes };
})(typeof globalThis !== 'undefined' ? globalThis : this);
