#!/usr/bin/env node
/* Reads billing cases as JSON on stdin, prints the UI's answer for each.
   tests/test_billing.py feeds the same cases to billing.py and compares. */
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
process.stdout.write(JSON.stringify(out));
