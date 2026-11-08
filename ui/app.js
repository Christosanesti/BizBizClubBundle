/* ══════════════════════════════════════════════════════════════════
   گیم سنتر — رابط کاربری (GSAP powered)
   ══════════════════════════════════════════════════════════════════ */
'use strict';

const FA = '۰۱۲۳۴۵۶۷۸۹';
const CUR = 'تومان';
const CONSOLES = ['1', '2', '3', '4'];

const fa = (s) => String(s).replace(/[0-9]/g, (d) => FA[+d]);
const fmtMoney = (n) => {
  const v = Math.round(Number(n) || 0);
  const s = Math.abs(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '٬');
  return (v < 0 ? '-' : '') + fa(s);
};
const pad2 = (x) => String(x).padStart(2, '0');
const hms = (sec) => {
  const t = Math.max(0, Math.floor(sec));
  return fa([Math.floor(t / 3600), Math.floor((t % 3600) / 60), t % 60].map(pad2).join(':'));
};
const hmsParts = (sec) => {
  const t = Math.max(0, Math.floor(sec));
  return [fa(pad2(Math.floor(t / 3600))), fa(pad2(Math.floor((t % 3600) / 60))), fa(pad2(t % 60))];
};
const fmtDur = (sec) => {
  const t = Math.max(0, Math.floor(sec));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60);
  if (h > 0) return `${fa(h)} ساعت و ${fa(m)} دقیقه`;
  if (m > 0) return `${fa(m)} دقیقه`;
  return `${fa(t)} ثانیه`;
};
const fmtClock = (isoStr) => {
  const d = new Date(isoStr);
  return fa(pad2(d.getHours()) + ':' + pad2(d.getMinutes()));
};
const toLocalInput = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;

/* ── digit helpers ────────────────────────────────────────────────
   A Persian keyboard sends ۱۰۰۰۰۰ — never let a price become 0 because
   of the digit set. Everything is normalized to ASCII before parsing.
   billing.js owns that parser so the timer and the server agree. */
const parseNum = GCBilling.num;

const groupNum = (n) => fmtMoney(n);

/* ── numeric stepper component ── */
function numStepper(opts = {}) {
  const { id = '', cls = '', value = 0, step = 1000, min = 0, max = '', compact = false,
    placeholder = '۰', label = '' } = opts;
  const v = Math.max(min, Math.round(Number(value) || 0));
  return `<div class="stepper${compact ? ' compact' : ''}" data-step="${step}" data-min="${min}" data-max="${max}">
    <button type="button" class="st-btn" data-d="-1" tabindex="-1" aria-label="کم کردن">−</button>
    <input${id ? ` id="${id}"` : ''} class="st-input${cls ? ' ' + cls : ''}" type="text"
      inputmode="numeric" autocomplete="off" dir="ltr" placeholder="${placeholder}"
      value="${v ? groupNum(v) : ''}" data-raw="${v}" aria-label="${label || 'مقدار عددی'}">
    <button type="button" class="st-btn" data-d="1" tabindex="-1" aria-label="افزودن">+</button>
  </div>`;
}

const isStepperInput = (node) => !!(node && node.classList && node.classList.contains('st-input'));

function stepperBounds(box) {
  const min = parseNum(box.dataset.min, 0);
  const max = box.dataset.max ? parseNum(box.dataset.max, 0) : Infinity;
  return { min, max };
}

function stepperWrite(input, value) {
  const box = input.closest('.stepper');
  const { min, max } = stepperBounds(box);
  let n = Math.round(Number(value) || 0);
  n = Math.max(min, Math.min(max, n));
  input.dataset.raw = String(n);
  box.dataset.value = String(n);
  const shown = n ? groupNum(n) : '';
  input.value = shown;
  if (document.activeElement === input) {
    try { input.setSelectionRange(shown.length, shown.length); } catch (_) { /* ignore */ }
  }
  return n;
}

function stepperNudge(input, dir, mult = 1) {
  const box = input.closest('.stepper');
  const step = (parseNum(box.dataset.step, 1) || 1) * mult;
  const n = stepperWrite(input, parseNum(input.dataset.raw, 0) + dir * step);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  return n;
}

/* read a value out of a stepper (or a plain input, tolerantly) */
function getNum(node, def = 0) {
  if (!node) return def;
  if (isStepperInput(node)) return parseNum(node.dataset.raw, def);
  return parseNum(node.value, def);
}

function setStepper(node, value) {
  if (!node) return 0;
  const input = isStepperInput(node) ? node : node.querySelector('.st-input');
  return input ? stepperWrite(input, value) : 0;
}

/* ── billing — the same math as billing.py, never a local copy ── */
const { bill: billFor, fmtMinutes } = GCBilling;

/* the wall clock a running session is measured with (ms, server stamped) */
const runStartMs = (run) => Number(run && (run.start_ms ?? Date.parse(run.start))) || 0;
const runSeconds = (run, atMs = Date.now()) => Math.max(0, (atMs - runStartMs(run)) / 1000);

/* one id per settle attempt, so a retried request cannot bill twice */
const uid = () => (window.crypto && crypto.randomUUID
  ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

/* ── animation toolkit ── */
const gsap = window.gsap || null;
const REDUCE = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const canAnim = !!gsap && !REDUCE;
const ACCENTS = { '1': '#38bdf8', '2': '#a78bfa', '3': '#34d399', '4': '#fbbf24' };

function animIn(el, vars = {}) {
  if (!el) return;
  if (!canAnim) { gsap && gsap.set(el, { clearProps: 'all' }); return; }
  gsap.from(el, { y: 14, opacity: 0, duration: .5, ease: 'power3.out', ...vars });
}
function pop(el, strength = 1.06) {
  if (!el || !canAnim) return;
  gsap.fromTo(el, { scale: strength }, { scale: 1, duration: .45, ease: 'elastic.out(1, .55)' });
}
function tweenNumber(node, to, opt = {}) {
  if (!node) return;
  const { dur = .7, format = fmtMoney } = opt;
  const from = Number(node.dataset.val || 0);
  node.dataset.val = to;
  if (node._tw) node._tw.kill();
  if (!canAnim || from === to) { node.textContent = format(to); return; }
  const o = { v: from };
  node._tw = gsap.to(o, {
    v: to, duration: dur, ease: 'power2.out', overwrite: true,
    onUpdate: () => { node.textContent = format(o.v); },
    onComplete: () => { node.textContent = format(to); },
  });
}

/* ── state ── */
let S = null;
const handleSel = JSON.parse(localStorage.getItem('gc-handles') || '{}');
CONSOLES.forEach((c) => { if (!handleSel[c]) handleSel[c] = 2; });

const $ = (id) => document.getElementById(id);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};

/* ── api ── */
async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
  let res, data;
  try {
    res = await fetch(path, opt);
    data = await res.json();
  } catch (e) {
    throw new Error('ارتباط با سرویس برقرار نشد.');
  }
  if (!res.ok || data.ok === false) throw new Error(data.error || 'خطای نامشخص');
  return data;
}

function mergeState(payload) {
  if (!payload) return;
  const base = S || {};
  const next = { ...base, ...payload };
  if (!payload.settings || !Object.keys(payload.settings).length) next.settings = base.settings;
  if (!payload.data_dir) next.data_dir = base.data_dir;
  S = next;
}

/* ── toast ── */
let toastTimer = null;
function toast(msg, kind = '') {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast ' + kind;
  t.hidden = false;
  const w = t.offsetWidth; // reflow for re-animation
  if (canAnim) {
    gsap.killTweensOf(t);
    gsap.fromTo(t, { y: 24, opacity: 0, scale: .96 },
      { y: 0, opacity: 1, scale: 1, duration: .5, ease: 'back.out(1.6)' });
  }
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    if (!canAnim) { t.hidden = true; return; }
    gsap.to(t, { y: 16, opacity: 0, duration: .25, ease: 'power2.in', onComplete: () => { t.hidden = true; } });
  }, kind === 'bad' ? 4200 : 2800);
}

/* ── modal plumbing ── */
let modalCleanup = null;
let modalClosing = false;

/* replace a node with a clean clone so listeners from the previous modal die */
function freshNode(id) {
  const old = $(id);
  const clone = old.cloneNode(false);
  old.replaceWith(clone);
  return clone;
}

function openModal(title, bodyHtml, footHtml, opts = {}) {
  if (modalCleanup) { modalCleanup(); modalCleanup = null; }
  const ov = $('overlay'), md = $('modal');
  if (gsap) { gsap.killTweensOf([ov, md]); }
  modalClosing = false;

  $('modalTitle').textContent = title;
  freshNode('modalBody').innerHTML = bodyHtml;
  freshNode('modalFoot').innerHTML = footHtml || '';
  md.className = 'modal' + (opts.wide ? ' wide' : '');
  ov.hidden = false;

  if (canAnim) {
    gsap.fromTo(ov, { opacity: 0 }, { opacity: 1, duration: .22, ease: 'power1.out' });
    gsap.fromTo(md, { y: 26, scale: .955, opacity: 0 },
      { y: 0, scale: 1, opacity: 1, duration: .5, ease: 'back.out(1.25)' });
    const items = $('modalBody').querySelectorAll('.kv .cell, .section-title, .drink-btn, .field, .de-row, table.arc tbody tr, .totals .row');
    if (items.length) {
      gsap.from(items, { y: 10, opacity: 0, duration: .38, ease: 'power2.out', stagger: .022, delay: .06 });
    }
  }
  return { body: $('modalBody'), foot: $('modalFoot') };
}

function closeModal(instant) {
  if (modalCleanup) { modalCleanup(); modalCleanup = null; }
  const ov = $('overlay'), md = $('modal');
  if (modalClosing) return;
  const finish = () => {
    ov.hidden = true;
    $('modalBody').innerHTML = '';
    $('modalFoot').innerHTML = '';
    if (gsap) gsap.set(md, { clearProps: 'all' });
    modalClosing = false;
  };
  if (!canAnim || instant) { finish(); return; }
  modalClosing = true;
  gsap.to(md, { y: 14, scale: .97, opacity: 0, duration: .17, ease: 'power2.in' });
  gsap.to(ov, { opacity: 0, duration: .18, onComplete: finish });
}

$('modalClose').addEventListener('click', () => closeModal());
$('overlay').addEventListener('mousedown', (e) => { if (e.target.id === 'overlay') closeModal(); });

/* styled confirm — replaces the browser dialog */
function askConfirm({ title, message, okLabel = 'تایید', cancelLabel = 'انصراف', danger = false }) {
  return new Promise((resolve) => {
    const m = openModal(title,
      `<p class="confirm-msg">${message}</p>`,
      `<button class="btn ghost" id="cfNo">${cancelLabel}</button>
       <div class="spacer"></div>
       <button class="btn ${danger ? 'danger' : 'ok'}" id="cfYes">${okLabel}</button>`);
    let done = false;
    const finish = (v) => {
      if (done) return;
      done = true;
      resolve(v);
    };
    m.foot.querySelector('#cfYes').addEventListener('click', () => { finish(true); closeModal(); });
    m.foot.querySelector('#cfNo').addEventListener('click', () => { finish(false); closeModal(); });
    modalCleanup = () => finish(false);
  });
}

/* ── global stepper behaviour (delegated — survives re-renders) ── */
document.addEventListener('input', (e) => {
  const input = e.target;
  if (!isStepperInput(input)) return;
  const box = input.closest('.stepper');
  const { max } = stepperBounds(box);
  let n = parseNum(input.value, 0);
  if (n < 0) n = 0;
  if (Number.isFinite(max) && n > max) n = max;
  input.dataset.raw = String(n);
  box.dataset.value = String(n);
  const shown = n ? groupNum(n) : '';
  if (input.value !== shown) {
    input.value = shown;
    try { input.setSelectionRange(shown.length, shown.length); } catch (_) { /* ignore */ }
  }
});

document.addEventListener('click', (e) => {
  const btn = e.target.closest('.stepper .st-btn');
  if (!btn) return;
  const box = btn.closest('.stepper');
  const input = box.querySelector('.st-input');
  if (!input) return;
  e.preventDefault();
  stepperNudge(input, parseNum(btn.dataset.d, 0));
});

document.addEventListener('keydown', (e) => {
  const input = e.target;
  if (!isStepperInput(input)) return;
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    e.preventDefault();
    stepperNudge(input, e.key === 'ArrowUp' ? 1 : -1, e.shiftKey ? 10 : 1);
  } else if ((e.key === 'Enter' || e.key === 'Escape') && input.closest('#modal')) {
    e.preventDefault();
    input.blur();
  }
});

document.addEventListener('focusin', (e) => {
  const input = e.target;
  if (!isStepperInput(input)) return;
  requestAnimationFrame(() => {
    try { input.select(); } catch (_) { /* ignore */ }
  });
});

document.addEventListener('focusout', (e) => {
  const input = e.target;
  if (!isStepperInput(input)) return;
  stepperWrite(input, parseNum(input.dataset.raw, 0));
});

/* ── render ── */
function render(opts = {}) {
  if (!S) return;
  const st = S.settings;
  document.title = st.shop_name + ' — دفتر روزانه';
  $('shopName').textContent = st.shop_name;
  $('todayLabel').textContent = S.today.jalali_long;
  $('dataPath').textContent = S.data_dir;
  $('staleBar').hidden = !S.is_stale;

  tweenNumber($('statTotal'), S.today.totals.total, { dur: opts.silent ? 0 : .8 });
  tweenNumber($('statCount'), S.today.totals.count, { dur: opts.silent ? 0 : .55, format: fa });
  $('statBusy').textContent = `${fa(Object.keys(S.running).length)} از ۴`;

  renderLog(opts);
  renderDrinkStats(opts);
  syncCards(opts);
  $('logCount').textContent = fa(S.today.sessions.length);
}

function renderLog(opts = {}) {
  const rows = S.today.sessions;
  const body = $('logBody');
  body.innerHTML = '';
  $('logEmpty').hidden = rows.length > 0;

  rows.forEach((s, i) => {
    const tr = el('tr');
    tr.dataset.id = s.id;
    const itemList = (s.items || []).map((it) => `${it.name} ×${fa(it.qty)}`).join('، ');
    const tip = [itemList, s.note].filter(Boolean).join(' — ');
    if (tip) tr.title = tip;
    tr.innerHTML = `
      <td class="num">${fa(i + 1)}</td>
      <td>دستگاه ${fa(s.console)} ${s.manual ? '<span class="pill manual">دستی</span>' : ''}</td>
      <td class="time">${fmtClock(s.start)}</td>
      <td class="time">${fmtClock(s.end)}</td>
      <td>${fmtDur(s.seconds)}</td>
      <td class="num">${fa(s.handles)} دسته</td>
      <td class="num">${fmtMoney(s.play)}</td>
      <td class="num" title="${itemList.replace(/"/g, '&quot;')}">${s.items_total ? fmtMoney(s.items_total) : '—'}</td>
      <td class="num total">${fmtMoney(s.total)}</td>
      <td><button class="row-del" title="حذف این ردیف">✕</button></td>`;
    body.appendChild(tr);
  });

  const t = S.today.totals;
  tweenNumber($('footPlay'), t.play, { dur: opts.silent ? 0 : .8 });
  tweenNumber($('footItems'), t.items, { dur: opts.silent ? 0 : .8 });
  tweenNumber($('footTotal'), t.total, { dur: opts.silent ? 0 : .9 });

  if (opts.newId) {
    const tr = body.querySelector(`tr[data-id="${opts.newId}"]`);
    if (tr) {
      if (canAnim) {
        gsap.from(tr, { x: -18, opacity: 0, duration: .55, ease: 'power3.out' });
        gsap.fromTo(tr, { backgroundColor: 'rgba(52,211,153,.22)' },
          { backgroundColor: 'rgba(52,211,153,0)', duration: 1.6, delay: .1, ease: 'power2.out' });
      }
      tr.scrollIntoView({ block: 'nearest' });
    }
  } else if (canAnim && rows.length && !opts.silent) {
    const trs = body.querySelectorAll('tr');
    gsap.from(trs, { y: 8, opacity: 0, duration: .32, stagger: .025, ease: 'power2.out' });
  }
}

function renderDrinkStats(opts = {}) {
  const agg = new Map();
  S.today.sessions.forEach((s) => (s.items || []).forEach((it) => {
    const a = agg.get(it.name) || { qty: 0, sum: 0 };
    a.qty += it.qty; a.sum += it.qty * it.price;
    agg.set(it.name, a);
  }));
  const box = $('drinkStats');
  box.innerHTML = '';
  if (!agg.size) {
    box.appendChild(el('div', 'drink-empty', 'امروز نوشیدنی فروخته نشده است.'));
    return;
  }
  const max = Math.max(...[...agg.values()].map((a) => a.qty));
  [...agg.entries()].sort((a, b) => b[1].qty - a[1].qty).forEach(([name, a]) => {
    const wrap = el('div', 'drink-item');
    wrap.innerHTML = `
      <div class="drink-line">
        <span class="n" title="${name}">${name}</span>
        <span class="q">×${fa(a.qty)}</span>
        <span class="p">${fmtMoney(a.sum)}</span>
      </div>
      <div class="drink-bar"><i></i></div>`;
    box.appendChild(wrap);
    const bar = wrap.querySelector('.drink-bar i');
    const pct = Math.max(6, (a.qty / max) * 100);
    if (canAnim && !opts.silent) {
      gsap.fromTo(bar, { width: '0%' }, { width: pct + '%', duration: .8, ease: 'power2.out' });
    } else bar.style.width = pct + '%';
  });
}

/* ── console cards ── */
const consolesEl = $('consoles');
const GAMEPAD = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M6.2 8.5h11.6c1.9 0 2.9 1.3 3.2 3l.8 4.4c.3 1.7-.5 2.6-1.6 2.6-1 0-1.5-.6-2.2-1.5l-.9-1.2H6.9l-.9 1.2c-.7.9-1.2 1.5-2.2 1.5-1.1 0-1.9-.9-1.6-2.6l.8-4.4c.3-1.7 1.3-3 3.2-3Z"/><path d="M7.5 12v3M6 13.5h3"/><circle cx="15.6" cy="12.6" r=".9" fill="currentColor"/><circle cx="17.6" cy="14.6" r=".9" fill="currentColor"/></svg>`;

function buildCards() {
  consolesEl.innerHTML = '';
  CONSOLES.forEach((c) => {
    const card = el('article', 'card');
    card.dataset.c = c;
    card.innerHTML = `<div class="sweep"></div>`;
    consolesEl.appendChild(card);
  });
}

function syncCards(opts = {}) {
  const st = S.settings;
  CONSOLES.forEach((c) => {
    const card = consolesEl.querySelector(`.card[data-c="${c}"]`);
    if (!card) return;
    const run = S.running[c];
    const h = handleSel[c];
    const rate = Number(st.rates[String(h)] || 0);
    const wasBusy = card.classList.contains('busy');

    if (run) {
      card.classList.add('busy');
      delete card.dataset.cost;
      card.innerHTML = `
        <div class="sweep"></div>
        <div class="card-top">
          <div class="cname"><span class="cicon">${GAMEPAD}</span>دستگاه ${fa(c)}</div>
          <div class="badge"><span class="dot"></span>در حال بازی</div>
        </div>
        <div class="timer"><span data-h>۰۰</span><span class="colon">:</span><span data-m>۰۰</span><span class="colon">:</span><span data-s class="sec">۰۰</span></div>
        <div class="step-track"><i data-step></i></div>
        <div class="meta-row"><span>شروع <b>${run.start_label}</b></span><span><b>${fa(run.handles)}</b> دسته</span></div>
        <div class="price-row"><span>هزینه تا این لحظه</span><span class="money" data-cost>۰</span></div>
        <div class="ctrl two">
          <button class="stop-btn">پایان و تسویه</button>
          <button class="cancel-btn" title="لغو بدون محاسبه">✕</button>
        </div>`;
      if (!wasBusy && canAnim && !opts.silent) {
        gsap.fromTo(card, { scale: .97 }, { scale: 1, duration: .55, ease: 'back.out(1.5)' });
        gsap.from(card.querySelector('.timer'), { opacity: 0, filter: 'blur(6px)', duration: .5, ease: 'power2.out' });
      }
    } else {
      card.classList.remove('busy');
      card.innerHTML = `
        <div class="sweep"></div>
        <div class="card-top">
          <div class="cname"><span class="cicon">${GAMEPAD}</span>دستگاه ${fa(c)}</div>
          <div class="badge"><span class="dot"></span>آزاد</div>
        </div>
        <div class="timer">۰۰<span class="colon">:</span>۰۰<span class="colon">:</span>۰۰</div>
        <div class="step-track"><i></i></div>
        <div class="meta-row"><span class="muted">آماده شروع</span><span>نرخ <b>${fa(h)}</b> دسته</span></div>
        <div class="price-row"><span>هزینه هر ساعت</span><span class="money">${fmtMoney(rate)}</span></div>
        <div class="handles">
          <span class="seg-thumb" aria-hidden="true"></span>
          ${[1, 2, 3, 4].map((n) => `<button data-h="${n}" class="${n === h ? 'on' : ''}" aria-pressed="${n === h}">${fa(n)} دسته</button>`).join('')}
        </div>
        <div class="ctrl"><button class="start-btn">شروع بازی</button></div>`;
      placeSegThumb(card);
      if (wasBusy && canAnim && !opts.silent) {
        gsap.fromTo(card, { boxShadow: `0 0 0 2px ${ACCENTS[c]}66` }, { boxShadow: '0 0 0 0 rgba(0,0,0,0)', duration: .9, ease: 'power2.out' });
      }
    }
  });
  tick();
}

/* slide the segmented control's thumb under the active handle button */
function placeSegThumb(card) {
  if (!card) return;
  const wrap = card.querySelector('.handles');
  const thumb = wrap && wrap.querySelector('.seg-thumb');
  if (!wrap || !thumb) return;
  const on = wrap.querySelector('button.on');
  if (!on) { thumb.style.width = '0px'; return; }
  const first = !thumb.dataset.ready;
  if (first) thumb.style.transition = 'none';
  thumb.style.left = on.offsetLeft + 'px';
  thumb.style.width = on.offsetWidth + 'px';
  if (first) {
    requestAnimationFrame(() => {
      thumb.style.transition = '';
      thumb.dataset.ready = '1';
    });
  }
}

function placeAllThumbs() {
  consolesEl.querySelectorAll('.card:not(.busy)').forEach(placeSegThumb);
}
window.addEventListener('resize', () => requestAnimationFrame(placeAllThumbs));

function tick() {
  if (!S) return;
  const now = Date.now();
  const st = S.settings;
  const stepSec = (Number(st.rounding) > 1 && st.round_mode !== 'exact') ? Number(st.rounding) * 60 : 60;

  CONSOLES.forEach((c) => {
    const run = S.running[c];
    if (!run) return;
    const card = consolesEl.querySelector(`.card[data-c="${c}"]`);
    if (!card) return;
    const sec = runSeconds(run, now);

    const [hh, mm, ss] = hmsParts(sec);
    const hNode = card.querySelector('[data-h]');
    if (hNode) {
      if (hNode.textContent !== hh) hNode.textContent = hh;
      const mNode = card.querySelector('[data-m]');
      if (mNode.textContent !== mm) mNode.textContent = mm;
      const sNode = card.querySelector('[data-s]');
      if (sNode && sNode.textContent !== ss) {
        sNode.textContent = ss;
        if (canAnim) {
          gsap.fromTo(sNode, { y: -7, opacity: .25 }, { y: 0, opacity: 1, duration: .3, ease: 'power3.out', overwrite: true });
        }
      }
    }

    const stepBar = card.querySelector('[data-step]');
    if (stepBar) stepBar.style.width = ((sec % stepSec) / stepSec) * 100 + '%';

    const cost = billFor(sec, run.rate, st).play;
    const costNode = card.querySelector('[data-cost]');
    if (costNode && card.dataset.cost !== String(cost)) {
      card.dataset.cost = String(cost);
      tweenNumber(costNode, cost, { dur: .5 });
      if (canAnim) pop(costNode, 1.08);
    }
  });
}
setInterval(tick, 500);

/* clock in the header */
function paintClock() {
  const d = new Date();
  $('clockNow').textContent = fa(pad2(d.getHours()) + ':' + pad2(d.getMinutes()));
}
setInterval(paintClock, 1000 * 15);

/* ── interactions on the console grid ── */
consolesEl.addEventListener('click', (e) => {
  const card = e.target.closest('.card');
  if (!card) return;
  const c = card.dataset.c;
  const hBtn = e.target.closest('.handles button');
  if (hBtn) {
    handleSel[c] = Number(hBtn.dataset.h);
    localStorage.setItem('gc-handles', JSON.stringify(handleSel));
    card.querySelectorAll('.handles button').forEach((b) => {
      b.classList.toggle('on', b === hBtn);
      b.setAttribute('aria-pressed', b === hBtn);
    });
    placeSegThumb(card);
    pop(hBtn, 1.12);
    if (canAnim) gsap.fromTo(card.querySelector('.price-row .money'), { opacity: .2 }, { opacity: 1, duration: .35 });
    // update the rate + label in place
    const rate = Number(S.settings.rates[String(handleSel[c])] || 0);
    card.querySelector('.meta-row span:last-child').innerHTML = `نرخ <b>${fa(handleSel[c])}</b> دسته`;
    card.querySelector('.price-row .money').textContent = fmtMoney(rate);
    return;
  }
  if (e.target.closest('.start-btn')) return startConsole(c);
  if (e.target.closest('.stop-btn')) return openStopModal(c);
  if (e.target.closest('.cancel-btn')) return cancelConsole(c);
});

/* 3D tilt */
let tiltRaf = 0;
consolesEl.addEventListener('pointermove', (e) => {
  if (!canAnim) return;
  const card = e.target.closest('.card');
  if (!card) return;
  const r = card.getBoundingClientRect();
  const px = (e.clientX - r.left) / r.width;
  const py = (e.clientY - r.top) / r.height;
  cancelAnimationFrame(tiltRaf);
  tiltRaf = requestAnimationFrame(() => {
    gsap.to(card, {
      rotateY: (px - .5) * 6, rotateX: (.5 - py) * 6,
      transformPerspective: 1000, scale: 1.012, duration: .35, ease: 'power2.out',
    });
  });
});
consolesEl.addEventListener('pointerleave', () => {
  consolesEl.querySelectorAll('.card').forEach((c) => {
    if (canAnim) gsap.to(c, { rotateX: 0, rotateY: 0, scale: 1, duration: .6, ease: 'elastic.out(1,.7)' });
  });
});

async function startConsole(c) {
  const card = consolesEl.querySelector(`.card[data-c="${c}"]`);
  const btn = card && card.querySelector('.start-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'در حال شروع…'; }
  try {
    const r = await api('/api/start', { console: c, handles: handleSel[c] });
    mergeState(r);
    render();
    toast(`دستگاه ${fa(c)} شروع شد — ${fmtMoney(r.settings.rates[String(r.running[c].handles)])} ${CUR} در ساعت`, 'ok');
  } catch (err) {
    toast(err.message, 'bad');
    if (btn) { btn.disabled = false; btn.textContent = 'شروع بازی'; }
  }
}

async function cancelConsole(c) {
  const yes = await askConfirm({
    title: `لغو بازی دستگاه ${fa(c)}`,
    message: 'این بازی بدون محاسبهٔ هزینه بسته می‌شود و در دفتر ثبت نخواهد شد.',
    okLabel: 'بله، لغو کن', danger: true,
  });
  if (!yes) return;
  try {
    const r = await api('/api/cancel', { console: c });
    mergeState(r.state);
    render();
    toast('بازی لغو شد.');
  } catch (err) { toast(err.message, 'bad'); }
}

/* ── settle modal ── */
function openStopModal(c) {
  const run = S.running[c];
  if (!run) return;
  const opId = uid();
  let items = [];

  const body = `
    <div class="kv">
      <div class="cell"><div class="k">شروع</div><div class="v">${run.start_label}</div></div>
      <div class="cell"><div class="k">مدت بازی</div><div class="v live" id="mDur">—</div></div>
      <div class="cell"><div class="k">دسته</div><div class="v">${fa(run.handles)}</div></div>
      <div class="cell"><div class="k">نرخ ساعتی</div><div class="v">${fmtMoney(run.rate)}</div></div>
    </div>
    <div class="section-title">نوشیدنی و خوراکی</div>
    <div class="drinks-grid" id="drinkPick">
      ${S.settings.drinks.length
        ? S.settings.drinks.map((d, i) => `<button class="drink-btn" data-i="${i}">
             <span class="dn">${d.name}</span><span class="dp">${fmtMoney(d.price)}</span></button>`).join('')
        : '<div class="drink-empty">منویی تعریف نشده — از تنظیمات اضافه کنید.</div>'}
    </div>
    <div class="section-title">صورتحساب</div>
    <ul class="bill" id="billList"></ul>
    <div class="inline" style="margin-top:10px">
      <div class="field"><label>مورد دلخواه</label><input id="customName" placeholder="مثلاً پیتزا" maxlength="40"></div>
      <div class="field" style="max-width:130px"><label>مبلغ</label><input id="customPrice" type="number" min="0" step="1000" placeholder="0"></div>
      <button class="btn ghost small" id="customAdd" style="height:38px">افزودن</button>
    </div>
    <div class="totals" id="mTotals"></div>`;

  const foot = `
    <button class="btn ghost" id="mCancel">انصراف</button>
    <div class="spacer"></div>
    <button class="btn ok" id="mConfirm">ثبت و آزادسازی دستگاه</button>`;

  const m = openModal(`تسویه حساب — دستگاه ${fa(c)}`, body, foot);

  /* one clock for the screen and for the receipt: whatever this returns for
     `end` is also what gets posted, so the bill can never disagree with the
     number the cashier just read out. */
  const calc = (atMs = Date.now()) => {
    const b = billFor(runSeconds(run, atMs), run.rate, S.settings);
    const itemsTotal = items.reduce((a, i) => a + i.price * i.qty, 0);
    return { ...b, itemsTotal, total: b.play + itemsTotal };
  };

  const renderTotals = (fresh, atMs = Date.now()) => {
    const c = calc(atMs);
    const dur = m.body.querySelector('#mDur');
    if (dur) dur.textContent = fmtDur(c.seconds);
    const box = m.body.querySelector('#mTotals');
    const prev = Number(box.dataset.total || 0);
    box.dataset.total = c.total;
    box.dataset.minutes = c.minutes;
    box.innerHTML = `
      <div class="row"><span>هزینه بازی (${fmtMinutes(c.minutes)} دقیقه)</span><span class="money">${fmtMoney(c.play)} ${CUR}</span></div>
      <div class="row"><span>نوشیدنی و خوراکی</span><span class="money">${fmtMoney(c.itemsTotal)} ${CUR}</span></div>
      <div class="row big"><span>مبلغ قابل پرداخت</span><span class="money" id="mGrand">${fmtMoney(c.total)} ${CUR}</span></div>`;
    const grand = m.body.querySelector('#mGrand');
    if (canAnim && fresh && prev !== c.total) pop(grand, 1.06);
    return c;
  };

  const renderBill = () => {
    const list = m.body.querySelector('#billList');
    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML = '<li class="bill-empty">موردی اضافه نشده است.</li>';
    } else {
      items.forEach((it, i) => {
        const li = el('li');
        li.innerHTML = `<span class="bn">${it.name}</span>
          <span class="bq">
            <button data-q="-1" data-i="${i}" aria-label="کم کردن">−</button>
            <span>${fa(it.qty)}</span>
            <button data-q="1" data-i="${i}" aria-label="افزودن">+</button>
          </span>
          <span class="bp">${fmtMoney(it.price * it.qty)}</span>
          <button class="bdel" data-del="${i}" title="حذف">✕</button>`;
        list.appendChild(li);
      });
      if (canAnim) gsap.from(list.children, { y: 6, opacity: 0, duration: .3, stagger: .03, ease: 'power2.out' });
    }
    renderTotals(true);
  };

  /* floating +price chip flying to the total */
  const flyChip = (fromEl, price) => {
    if (!canAnim) return;
    const a = fromEl.getBoundingClientRect();
    const target = m.body.querySelector('#mTotals');
    if (!target) return;
    const b = target.getBoundingClientRect();
    const chip = el('div', 'fly-chip', `+${fmtMoney(price)}`);
    chip.style.left = a.left + a.width / 2 + 'px';
    chip.style.top = a.top + a.height / 2 + 'px';
    document.body.appendChild(chip);
    gsap.timeline({ onComplete: () => chip.remove() })
      .to(chip, { y: -14, scale: 1.12, duration: .22, ease: 'power2.out' })
      .to(chip, {
        x: b.left + b.width / 2 - (a.left + a.width / 2),
        y: b.top + b.height / 2 - (a.top + a.height / 2),
        scale: .5, opacity: 0, duration: .55, ease: 'power2.inOut',
      });
  };

  m.body.querySelector('#drinkPick').addEventListener('click', (e) => {
    const b = e.target.closest('.drink-btn');
    if (!b) return;
    const d = S.settings.drinks[Number(b.dataset.i)];
    if (!d) return;
    const found = items.find((x) => x.name === d.name && x.price === d.price);
    if (found) found.qty += 1;
    else items.push({ name: d.name, price: d.price, qty: 1 });
    pop(b, 1.08);
    flyChip(b, d.price);
    renderBill();
  });

  m.body.querySelector('#billList').addEventListener('click', (e) => {
    const q = e.target.closest('[data-q]');
    const del = e.target.closest('[data-del]');
    if (q) {
      const i = Number(q.dataset.i);
      const it = items[i];
      if (!it) return;
      it.qty += Number(q.dataset.q);
      if (it.qty <= 0) items.splice(i, 1);
      renderBill();
    } else if (del) {
      items.splice(Number(del.dataset.del), 1);
      renderBill();
    }
  });

  m.body.querySelector('#customAdd').addEventListener('click', () => {
    const name = m.body.querySelector('#customName').value.trim();
    const price = Number(m.body.querySelector('#customPrice').value) || 0;
    if (!name || price <= 0) return toast('نام و مبلغ مورد دلخواه را وارد کنید.', 'bad');
    const found = items.find((x) => x.name === name && x.price === price);
    if (found) found.qty += 1; else items.push({ name, price, qty: 1 });
    m.body.querySelector('#customName').value = '';
    m.body.querySelector('#customPrice').value = '';
    renderBill();
  });

  let iv = 0;
  const startTicking = () => {
    clearInterval(iv);
    iv = setInterval(() => { if ($('overlay').hidden) return renderTotals(false); }, 1000);
  };

  m.foot.querySelector('#mCancel').addEventListener('click', () => closeModal());
  m.foot.querySelector('#mConfirm').addEventListener('click', async () => {
    const btn = m.foot.querySelector('#mConfirm');
    /* freeze the clock and repaint with the exact instant that gets posted —
       the server bills this timestamp, so screen and book always match */
    const endMs = Date.now();
    clearInterval(iv);
    const shown = renderTotals(false, endMs);
    btn.disabled = true;
    btn.textContent = 'در حال ثبت…';
    try {
      const r = await api('/api/stop', { console: c, items, end_ms: endMs, op_id: opId });
      mergeState(r.state);
      closeModal();
      render({ newId: r.session.id });
      burst(c);
      toast(`دستگاه ${fa(c)} تسویه شد — ${fmtMoney(r.session.total)} ${CUR}`, 'ok');
      if (r.session.total !== shown.total) {
        toast(`مبلغ ثبت‌شده: ${fmtMoney(r.session.total)} ${CUR}`, 'ok');
      }
    } catch (err) {
      btn.disabled = false;
      btn.textContent = 'ثبت و آزادسازی دستگاه';
      startTicking();
      toast(err.message, 'bad');
    }
  });

  renderTotals(false);
  modalCleanup = () => clearInterval(iv);
  startTicking();
}

function burst(consoleId) {
  if (typeof window.confetti !== 'function' || REDUCE) return;
  const colors = [ACCENTS[consoleId] || '#5b8cff', '#a78bfa', '#34d399', '#fbbf24', '#ffffff'];
  window.confetti({
    particleCount: 70, spread: 68, startVelocity: 34, gravity: .9,
    ticks: 160, scalar: .85, origin: { x: .5, y: .62 }, colors, zIndex: 100,
  });
}

/* ── manual entry ── */
$('btnManual').addEventListener('click', () => {
  const nowD = new Date();
  const past = new Date(nowD.getTime() - 90 * 60000);
  const body = `
    <div class="grid2">
      <div class="field"><label>دستگاه</label>
        <select id="mnConsole">${CONSOLES.map((c) => `<option value="${c}">دستگاه ${fa(c)}</option>`).join('')}</select>
      </div>
      <div class="field"><label>تعداد دسته</label>
        <select id="mnHandles">${[1, 2, 3, 4].map((n) => `<option value="${n}" ${n === 2 ? 'selected' : ''}>${fa(n)} دسته</option>`).join('')}</select>
      </div>
      <div class="field"><label>زمان شروع</label><input type="datetime-local" id="mnStart" value="${toLocalInput(past)}"></div>
      <div class="field"><label>زمان پایان</label><input type="datetime-local" id="mnEnd" value="${toLocalInput(nowD)}"></div>
      <div class="field"><label>مبلغ متفرقه (اختیاری)</label><input type="number" min="0" step="1000" id="mnExtra" placeholder="0"></div>
      <div class="field"><label>نام متفرقه</label><input id="mnExtraName" placeholder="مثلاً نوشابه" maxlength="40"></div>
    </div>
    <div class="field"><label>توضیح (اختیاری)</label><input id="mnNote" placeholder="مثلاً مهمان آقای رضایی" maxlength="80"></div>
    <div class="totals" id="mnTotals"></div>`;
  const foot = `<button class="btn ghost" id="mnCancel">انصراف</button><div class="spacer"></div>
    <button class="btn" id="mnSave">ثبت در دفتر روز</button>`;
  const m = openModal('ثبت دستی بازی', body, foot);

  const preview = () => {
    const iStart = m.body.querySelector('#mnStart'), iEnd = m.body.querySelector('#mnEnd');
    const iHandles = m.body.querySelector('#mnHandles'), iExtra = m.body.querySelector('#mnExtra');
    const iTotals = m.body.querySelector('#mnTotals');
    if (!iStart || !iEnd || !iHandles || !iExtra || !iTotals) return;
    const s = new Date(iStart.value);
    const e = new Date(iEnd.value);
    const h = Number(iHandles.value);
    const rate = Number(S.settings.rates[String(h)] || 0);
    const sec = Math.max(0, (e - s) / 1000);
    const b = billFor(sec, rate, S.settings);
    const extra = Number(iExtra.value) || 0;
    iTotals.innerHTML = `
      <div class="row"><span>مدت: ${fmtDur(sec)}</span><span class="money">${fmtMinutes(b.minutes)} دقیقه محاسبه</span></div>
      <div class="row"><span>هزینه بازی</span><span class="money">${fmtMoney(b.play)} ${CUR}</span></div>
      <div class="row big"><span>جمع این ردیف</span><span class="money">${fmtMoney(b.play + extra)} ${CUR}</span></div>`;
  };
  m.body.addEventListener('input', preview);
  preview();

  m.foot.querySelector('#mnCancel').addEventListener('click', () => closeModal());
  m.foot.querySelector('#mnSave').addEventListener('click', async () => {
    const payload = {
      console: m.body.querySelector('#mnConsole').value,
      handles: Number(m.body.querySelector('#mnHandles').value),
      start: m.body.querySelector('#mnStart').value,
      end: m.body.querySelector('#mnEnd').value,
      extra: Number(m.body.querySelector('#mnExtra').value) || 0,
      extra_name: m.body.querySelector('#mnExtraName').value,
      note: m.body.querySelector('#mnNote').value,
    };
    if (!payload.start || !payload.end) return toast('زمان شروع و پایان را وارد کنید.', 'bad');
    try {
      const r = await api('/api/manual', payload);
      mergeState(r.state);
      closeModal();
      const last = S.today.sessions[S.today.sessions.length - 1];
      render({ newId: last && last.id });
      toast('ردیف دستی ثبت شد.', 'ok');
    } catch (err) { toast(err.message, 'bad'); }
  });
});

/* ── settings ── */
$('btnSettings').addEventListener('click', () => {
  const st = S.settings;
  const roundVal = (st.round_mode === 'exact' ? 'exact' : st.round_mode) + ':' + st.rounding;
  const roundOpts = [
    ['exact:1', 'دقیق (بر اساس هر دقیقه)'],
    ['up:5', 'هر ۵ دقیقه — گرد به بالا'],
    ['up:10', 'هر ۱۰ دقیقه — گرد به بالا'],
    ['up:15', 'هر ۱۵ دقیقه — گرد به بالا'],
    ['up:30', 'هر نیم ساعت — گرد به بالا'],
    ['up:60', 'هر ساعت — گرد به بالا'],
    ['nearest:5', 'هر ۵ دقیقه — نزدیک‌ترین'],
    ['nearest:15', 'هر ۱۵ دقیقه — نزدیک‌ترین'],
  ];
  const body = `
    <div class="field"><label>نام مجموعه</label><input id="stName" value="${st.shop_name.replace(/"/g, '&quot;')}" maxlength="40"></div>
    <div class="section-title">نرخ ساعتی هر دستگاه (${CUR})</div>
    <div class="grid4">
      ${[1, 2, 3, 4].map((n) => `<div class="field"><label>${fa(n)} دسته</label>
        <input type="number" min="0" step="5000" id="stRate${n}" value="${st.rates[String(n)]}"></div>`).join('')}
    </div>
    <div class="section-title">نحوه محاسبه زمان</div>
    <div class="grid2">
      <div class="field"><label>گرد کردن زمان</label>
        <select id="stRound">${roundOpts.map(([v, l]) => `<option value="${v}" ${v === roundVal ? 'selected' : ''}>${l}</option>`).join('')}</select>
      </div>
      <div class="field"><label>حداقل زمان محاسبه (دقیقه)</label>
        <input type="number" min="0" step="5" id="stMin" value="${st.min_minutes}"></div>
    </div>
    <div class="section-title">منوی نوشیدنی و خوراکی</div>
    <div class="drinks-edit" id="drinkEdit">
      ${st.drinks.map((d) => `<div class="de-row">
          <input class="de-name" value="${d.name.replace(/"/g, '&quot;')}" maxlength="40" placeholder="نام">
          <input class="de-price" type="number" min="0" step="1000" value="${d.price}" placeholder="قیمت">
          <button class="rm" title="حذف">✕</button></div>`).join('')}
    </div>
    <button class="btn ghost small" id="drinkAdd" style="margin-top:10px">+ افزودن مورد جدید</button>`;
  const foot = `<button class="btn ghost" id="stCancel">انصراف</button><div class="spacer"></div>
    <button class="btn" id="stSave">ذخیره تنظیمات</button>`;
  const m = openModal('تنظیمات', body, foot, { wide: true });

  const drinksBox = m.body.querySelector('#drinkEdit');
  const addRow = (name = '', price = '') => {
    const row = el('div', 'de-row');
    row.innerHTML = `<input class="de-name" value="${name}" maxlength="40" placeholder="نام">
      <input class="de-price" type="number" min="0" step="1000" value="${price}" placeholder="قیمت">
      <button class="rm" title="حذف">✕</button>`;
    drinksBox.appendChild(row);
    if (canAnim) gsap.from(row, { y: 8, opacity: 0, duration: .3, ease: 'power2.out' });
  };
  m.body.querySelector('#drinkAdd').addEventListener('click', () => addRow());
  drinksBox.addEventListener('click', (e) => {
    if (!e.target.classList.contains('rm')) return;
    const row = e.target.closest('.de-row');
    if (canAnim) gsap.to(row, { height: 0, opacity: 0, marginBottom: -6, duration: .22, onComplete: () => row.remove() });
    else row.remove();
  });

  m.foot.querySelector('#stCancel').addEventListener('click', () => closeModal());
  m.foot.querySelector('#stSave').addEventListener('click', async () => {
    const [mode, step] = m.body.querySelector('#stRound').value.split(':');
    const rates = {};
    [1, 2, 3, 4].forEach((n) => { rates[String(n)] = Number(m.body.querySelector('#stRate' + n).value) || 0; });
    const drinks = [...drinksBox.querySelectorAll('.de-row')].map((r) => ({
      name: r.querySelector('.de-name').value.trim(),
      price: Number(r.querySelector('.de-price').value) || 0,
    })).filter((d) => d.name);
    const payload = {
      shop_name: m.body.querySelector('#stName').value,
      rates, rounding: Number(step), round_mode: mode,
      min_minutes: Number(m.body.querySelector('#stMin').value) || 0,
      drinks,
    };
    try {
      await api('/api/settings', payload);
      mergeState(await api('/api/state'));
      closeModal();
      render();
      toast('تنظیمات ذخیره شد.', 'ok');
    } catch (err) { toast(err.message, 'bad'); }
  });
});

/* ── close the day ── */
async function closeDayFlow() {
  const t = S.today.totals;
  if (Object.keys(S.running).length) return toast('ابتدا دستگاه‌های فعال را تسویه کنید.', 'bad');
  if (!t.count) return toast('امروز هیچ حسابی ثبت نشده است.', 'bad');

  const body = `
    <div class="kv">
      <div class="cell"><div class="k">تاریخ</div><div class="v">${S.today.jalali_long}</div></div>
      <div class="cell"><div class="k">تعداد حساب</div><div class="v">${fa(t.count)}</div></div>
      <div class="cell"><div class="k">جمع کل</div><div class="v">${fmtMoney(t.total)} ${CUR}</div></div>
    </div>
    <div class="totals">
      <div class="row"><span>درآمد بازی</span><span class="money">${fmtMoney(t.play)} ${CUR}</span></div>
      <div class="row"><span>فروش نوشیدنی</span><span class="money">${fmtMoney(t.items)} ${CUR}</span></div>
      <div class="row big"><span>جمع صندوق</span><span class="money">${fmtMoney(t.total)} ${CUR}</span></div>
    </div>
    <p class="note-line">با بستن روز، این حساب در «دفتر روزها» بایگانی می‌شود و دفتر تازه‌ای باز می‌شود.
      پیش از بستن می‌توانید خروجی Excel بگیرید یا نسخهٔ چاپی تهیه کنید.</p>`;
  const foot = `<button class="btn ghost" id="cdCancel">انصراف</button>
    <button class="btn ghost" id="cdCsv">خروجی Excel</button>
    <button class="btn ghost" id="cdPrint">چاپ</button>
    <div class="spacer"></div>
    <button class="btn warn" id="cdOk">بستن روز و شروع روز جدید</button>`;
  const m = openModal('بستن حساب روز', body, foot);

  m.foot.querySelector('#cdCancel').addEventListener('click', () => closeModal());
  m.foot.querySelector('#cdCsv').addEventListener('click', () => { window.location.href = '/api/export.csv'; });
  m.foot.querySelector('#cdPrint').addEventListener('click', () => printDay(todayPayload()));
  m.foot.querySelector('#cdOk').addEventListener('click', async () => {
    try {
      const r = await api('/api/close-day', {});
      mergeState(await api('/api/state'));
      closeModal();
      render({ silent: true });
      const s = r.summary;
      const body2 = `
        <div class="totals">
          <div class="row"><span>تاریخ بسته‌شده</span><span class="money">${s.jalali_long}</span></div>
          <div class="row"><span>تعداد حساب</span><span class="money">${fa(s.count)}</span></div>
          <div class="row"><span>درآمد بازی</span><span class="money">${fmtMoney(s.play)} ${CUR}</span></div>
          <div class="row"><span>فروش نوشیدنی</span><span class="money">${fmtMoney(s.items)} ${CUR}</span></div>
          <div class="row big"><span>جمع صندوق</span><span class="money">${fmtMoney(s.total)} ${CUR}</span></div>
        </div>
        <p class="note-line">روز جدید باز شد. موفق باشید ✨</p>`;
      const m2 = openModal('روز بسته شد', body2, '<div class="spacer"></div><button class="btn" id="ok">باشه</button>');
      m2.foot.querySelector('#ok').addEventListener('click', () => closeModal());
      if (typeof window.confetti === 'function' && !REDUCE) {
        window.confetti({ particleCount: 120, spread: 90, origin: { y: .55 }, colors: ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24'] });
      }
      toast('روز بسته و بایگانی شد.', 'ok');
    } catch (err) { toast(err.message, 'bad'); }
  });
}
$('btnCloseDay').addEventListener('click', () => closeDayFlow());
$('btnCloseStale').addEventListener('click', () => closeDayFlow());

/* ── printing ── */
function todayPayload() {
  return {
    sessions: S.today.sessions,
    totals: S.today.totals,
    title: S.today.jalali_long,
  };
}

function printDay(day) {
  const rows = (day.sessions || []).map((s, i) => `
    <tr>
      <td>${fa(i + 1)}</td>
      <td>دستگاه ${fa(s.console)}</td>
      <td>${fmtClock(s.start)}</td>
      <td>${fmtClock(s.end)}</td>
      <td>${fa(Math.round(s.minutes))}</td>
      <td>${fa(s.handles)}</td>
      <td>${fmtMoney(s.play)}</td>
      <td>${fmtMoney(s.items_total)}</td>
      <td>${fmtMoney(s.total)}</td>
      <td>${(s.items || []).map((it) => `${it.name} ×${fa(it.qty)}`).join('، ')}</td>
    </tr>`).join('');
  const t = day.totals || { play: 0, items: 0, total: 0, count: 0 };
  $('printArea').innerHTML = `
    <h1>${S.settings.shop_name} — حساب روزانه</h1>
    <div class="pmeta">${day.title || S.today.jalali_long} · ${fa(t.count)} حساب · چاپ‌شده در ${fa(new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }))}</div>
    <table>
      <thead><tr>
        <th>#</th><th>دستگاه</th><th>شروع</th><th>پایان</th><th>دقیقه</th>
        <th>دسته</th><th>بازی</th><th>نوشیدنی</th><th>جمع</th><th>اقلام</th>
      </tr></thead>
      <tbody>${rows || '<tr><td colspan="10">بدون حساب</td></tr>'}</tbody>
      <tfoot>
        <tr><td colspan="6">جمع بازی</td><td colspan="4">${fmtMoney(t.play)} ${CUR}</td></tr>
        <tr><td colspan="6">جمع نوشیدنی</td><td colspan="4">${fmtMoney(t.items)} ${CUR}</td></tr>
        <tr><td colspan="6">جمع کل</td><td colspan="4">${fmtMoney(t.total)} ${CUR}</td></tr>
      </tfoot>
    </table>
    <div class="sign"><span>امضای مسئول شیفت: ....................</span><span>تاریخ: ....../....../......</span></div>`;
  window.print();
}

/* ── archive ── */
function dayTable(day) {
  const rows = day.sessions || [];
  return `
    <div class="table-wrap" style="max-height:50vh">
      <table class="log">
        <thead><tr><th>#</th><th>دستگاه</th><th>شروع</th><th>پایان</th><th>مدت</th><th>دسته</th>
        <th>بازی</th><th>نوشیدنی</th><th>جمع</th></tr></thead>
        <tbody>
          ${rows.map((s, i) => `<tr>
            <td class="num">${fa(i + 1)}</td>
            <td>دستگاه ${fa(s.console)} ${s.manual ? '<span class="pill manual">دستی</span>' : ''}</td>
            <td class="time">${fmtClock(s.start)}</td>
            <td class="time">${fmtClock(s.end)}</td>
            <td>${fmtDur(s.seconds)}</td>
            <td class="num">${fa(s.handles)}</td>
            <td class="num">${fmtMoney(s.play)}</td>
            <td class="num">${s.items_total ? fmtMoney(s.items_total) : '—'}</td>
            <td class="num total">${fmtMoney(s.total)}</td></tr>`).join('') ||
            '<tr><td colspan="9" style="text-align:center;color:var(--muted)">خالی</td></tr>'}
        </tbody>
      </table>
    </div>
    <div class="totals" style="margin-top:14px">
      <div class="row"><span>درآمد بازی</span><span class="money">${fmtMoney(day.totals.play)} ${CUR}</span></div>
      <div class="row"><span>فروش نوشیدنی</span><span class="money">${fmtMoney(day.totals.items)} ${CUR}</span></div>
      <div class="row big"><span>جمع روز</span><span class="money">${fmtMoney(day.totals.total)} ${CUR}</span></div>
    </div>`;
}

$('btnArchive').addEventListener('click', async () => {
  let days = [];
  try {
    days = (await api('/api/days')).days;
  } catch (err) { return toast(err.message, 'bad'); }

  const body = days.length ? `
    <table class="arc">
      <thead><tr><th>تاریخ</th><th>بسته‌شده</th><th>حساب</th><th>بازی</th><th>نوشیدنی</th><th>جمع</th></tr></thead>
      <tbody>
        ${days.map((d) => `<tr data-f="${d.file}">
          <td>${d.jalali_long}</td>
          <td>${d.closed_time}</td>
          <td>${fa(d.count)}</td>
          <td>${fmtMoney(d.play)}</td>
          <td>${fmtMoney(d.items)}</td>
          <td class="tot">${fmtMoney(d.total)}</td></tr>`).join('')}
      </tbody>
    </table>` : '<div class="empty" style="padding:26px"><p>هنوز روزی بایگانی نشده است.</p><span>با «بستن روز» حساب‌ها اینجا آرشیو می‌شوند.</span></div>';

  const m = openModal('دفتر روزها', body, '<div class="spacer"></div><button class="btn ghost" id="arcClose">بستن</button>', { wide: true });
  m.foot.querySelector('#arcClose').addEventListener('click', () => closeModal());

  m.body.addEventListener('click', async (e) => {
    const tr = e.target.closest('tr[data-f]');
    if (!tr) return;
    const f = tr.dataset.f;
    try {
      const day = (await api('/api/day?f=' + encodeURIComponent(f))).day;
      const m2 = openModal('حساب ' + day.jalali_long, dayTable(day),
        `<button class="btn ghost" id="dCsv">خروجی Excel</button>
         <button class="btn ghost" id="dPrint">چاپ</button>
         <div class="spacer"></div><button class="btn ghost" id="dBack">بازگشت</button>`, { wide: true });
      m2.foot.querySelector('#dCsv').addEventListener('click', () => {
        window.location.href = '/api/export.csv?f=' + encodeURIComponent(f);
      });
      m2.foot.querySelector('#dPrint').addEventListener('click', () => {
        printDay({ sessions: day.sessions, totals: day.totals, title: day.jalali_long });
      });
      m2.foot.querySelector('#dBack').addEventListener('click', () => $('btnArchive').click());
    } catch (err) { toast(err.message, 'bad'); }
  });
});

/* ── row delete ── */
$('logBody').addEventListener('click', async (e) => {
  const btn = e.target.closest('.row-del');
  if (!btn) return;
  const tr = btn.closest('tr');
  const s = S.today.sessions.find((x) => x.id === tr.dataset.id);
  if (!s) return;
  const yes = await askConfirm({
    title: 'حذف ردیف',
    message: `ردیف دستگاه ${fa(s.console)} با مبلغ ${fmtMoney(s.total)} ${CUR} از دفتر امروز حذف شود؟ این کار جمع روز را تغییر می‌دهد.`,
    okLabel: 'حذف کن', danger: true,
  });
  if (!yes) return;
  if (canAnim) gsap.to(tr, { opacity: 0, x: 24, duration: .25, ease: 'power2.in' });
  try {
    const r = await api('/api/delete', { id: s.id });
    mergeState(r.state);
    render();
    toast('ردیف حذف شد.', 'ok');
  } catch (err) { toast(err.message, 'bad'); render(); }
});

/* ── misc buttons ── */
$('btnCsv').addEventListener('click', () => {
  window.location.href = '/api/export.csv';
  toast('فایل اکسل در پوشهٔ دانلود ذخیره می‌شود.');
});
$('btnPrint').addEventListener('click', () => printDay(todayPayload()));

/* ── keyboard ── */
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeModal(); return; }
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
  if (!$('overlay').hidden) return;
  if (['1', '2', '3', '4'].includes(e.key)) {
    if (S && S.running[e.key]) openStopModal(e.key);
    else if (S) startConsole(e.key);
  }
});

/* ── boot ── */
async function boot() {
  try {
    mergeState(await api('/api/state'));
    buildCards();
    render({ silent: true });
    paintClock();
    document.body.classList.remove('preload');
    if (canAnim) {
      gsap.from('.topbar', { y: -18, opacity: 0, duration: .6, ease: 'power3.out' });
      gsap.from('.card', { y: 26, opacity: 0, scale: .97, duration: .6, stagger: .06, ease: 'power3.out', delay: .05 });
      gsap.from('.lower', { y: 20, opacity: 0, duration: .6, ease: 'power3.out', delay: .12 });
    }
  } catch (err) {
    document.body.innerHTML = `<div style="margin:auto;padding:40px;text-align:center;color:#ff9ba4">
      <h2>سرویس گیم سنتر پاسخ نمی‌دهد</h2><p>${err.message}</p></div>`;
  }
}
boot();

/* keep several windows in sync */
setInterval(async () => {
  if (!S || !$('overlay').hidden) return;
  try {
    const data = await api('/api/state');
    delete data.ok;
    const changed = JSON.stringify(data.running) !== JSON.stringify(S.running)
      || JSON.stringify(data.today.sessions) !== JSON.stringify(S.today.sessions)
      || JSON.stringify(data.settings) !== JSON.stringify(S.settings)
      || data.today.jalali_long !== S.today.jalali_long;
    mergeState(data);
    if (changed) render();
  } catch (_) { /* ignore */ }
}, 5000);
