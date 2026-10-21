/**
 * FRED-outage regression. The page is generated with MFD_FORCE_FRED_CACHE=1 (every live FRED
 * request fails, so only the archived official CSVs are available) and written to
 * index-degraded.html. The page must still render every v2 section, label FRED rows as cached
 * in the data-health table and never describe cached rows as current.
 *
 *   MFD_FORCE_FRED_CACHE=1 MFD_OUTPUT=index-degraded.html python generate_dashboard.py
 *   node test_dashboard_fred_cache.mjs index-degraded.html
 */
import { chromium } from 'playwright';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2] || 'index-degraded.html';
if (!existsSync(resolve(src))) { console.error(`FAIL: target not found: ${src}`); process.exit(1); }

const failures = [];
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) failures.push(name);
};

const launchOpts = process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {};
const browser = await chromium.launch(launchOpts);
try {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  await page.goto(pathToFileURL(resolve(src)).href, { waitUntil: 'load' });
  await page.evaluate(() => document.querySelectorAll('details.sec').forEach((d) => { d.open = true; }));
  await page.waitForFunction(() => !!document.querySelector('#sec-credit .main-svg'), null, { timeout: 60000 });

  const s = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('[data-testid="health-table"] tbody tr')].map((tr) => [...tr.children].map((td) => td.textContent.trim()));
    const fred = rows.filter((r) => r[0].startsWith('FRED '));
    return {
      chip: (document.querySelector('[data-testid="health-chip"]') || {}).textContent || '',
      fredTotal: fred.length,
      fredCached: fred.filter((r) => r[3] === 'cached').length,
      fredCurrent: fred.filter((r) => r[3] === 'current').length,
      tiles: document.querySelectorAll('[data-testid="scorecard"] .score').length,
      sections: ['section-funding', 'section-credit', 'section-rates', 'section-fed-bs'].map((id) => !!document.querySelector(`[data-testid="${id}"]`)),
      creditCards: document.querySelectorAll('[data-testid="section-credit"] .mc').length,
    };
  });
  check('health chip reports cached sources', /\d+ cached/.test(s.chip), s.chip);
  check('FRED rows exist in the health table', s.fredTotal >= 30, String(s.fredTotal));
  check('every non-stale FRED row is labelled cached, none current', s.fredCurrent === 0 && s.fredCached > 0, `cached=${s.fredCached} current=${s.fredCurrent}`);
  check('scorecard still has six tiles', s.tiles === 6, String(s.tiles));
  check('v2 sections still render', s.sections.every(Boolean), JSON.stringify(s.sections));
  check('credit cards still render', s.creditCards >= 6, String(s.creditCards));
  check('no console errors', errors.length === 0, errors.slice(0, 3).join(' | '));
} finally {
  await browser.close();
}
if (failures.length) { console.error(`\n${failures.length} check(s) failed.`); process.exit(1); }
console.log('\nAll FRED-cache checks passed.');
