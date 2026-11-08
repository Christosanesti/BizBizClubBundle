#!/usr/bin/env node
/* Reads billing cases as JSON on stdin, prints the UI's answer for each.
   tests/test_billing.py feeds the same cases to billing.py and compares.

   The output is escaped to pure ASCII on purpose: the Python side decodes this
   with the machine's locale, and a Windows runner is not UTF-8 by default.
   Persian digits must not depend on the console code page. */
'use strict';

const fs = require('fs');
const path = require('path');

require(path.join(__dirname, '..', 'ui', 'billing.js'));
const B = globalThis.GCBilling;

const cases = JSON.parse(fs.readFileSync(0, 'utf8') || '[]');
const out = cases.map((c) => {
  const b = B.bill(c.sec, c.rate, c.settings);
  return {
    billMinutes: B.billMinutes(c.sec, c.settings),
    minutes: b.minutes,
    play: b.play,
    fmtMinutes: B.fmtMinutes(b.minutes),
  };
});

const ascii = JSON.stringify(out).replace(
  /[\u0080-\uffff]/g,
  (ch) => '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0'),
);
process.stdout.write(ascii);
