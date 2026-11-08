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

  function fa(s) {
    return String(s).replace(/[0-9]/g, (d) => FA_DIGITS[+d]);
  }

  /* 25 → ۲۵ · 24.6 → ۲۴٫۶ */
  function fmtMinutes(m) {
    const v = round2(m);
    const s = Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
    return fa(s.replace('.', '٫'));
  }

  root.GCBilling = { num, roundHalfUp, round2, billMinutes, playCost, bill, fmtMinutes };
})(typeof globalThis !== 'undefined' ? globalThis : this);
