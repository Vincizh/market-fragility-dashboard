/**
 * Browser-level regression checks for the generated dashboard.
 *
 * Guards two production failure modes in the Dollar Funding Pressure section:
 *   1. a chart renders but every KPI collapses to an em dash on a frozen series;
 *   2. one unavailable leg (reserves / TGA / SOFR) blanks the whole panel.
 *
 * Runs against the deployment-style static artifact (index.html) or a live URL.
 *
 *   node test_dashboard_browser.mjs [fileOrUrl] [--max-stale-days=6]
 *
 * Set PLAYWRIGHT_CHROMIUM_PATH to use a Chromium binary outside the Playwright
 * cache (needed on distros Playwright has no download for); CI leaves it unset.
 */
import { chromium } from 'playwright';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
const staleArg = args.find((a) => a.startsWith('--max-stale-days='));
const MAX_STALE_DAYS = staleArg ? Number(staleArg.split('=')[1]) : 6;
const target = args.find((a) => !a.startsWith('--')) || 'index.html';
const url = /^https?:/.test(target)
  ? target
  : (existsSync(resolve(target)) ? pathToFileURL(resolve(target)).href : null);
if (!url) {
  console.error(`FAIL: target not found: ${target}`);
  process.exit(1);
}

const failures = [];
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) failures.push(name + (detail ? ': ' + detail : ''));
};

const viewports = [
  { label: 'desktop', width: 1440, height: 1000, isMobile: false },
  { label: 'mobile', width: 390, height: 844, isMobile: true },
];

const CHART_IDS = ['chart-sofr-iorb', 'chart-fp-reserves', 'chart-fp-tga'];
const launchOpts = process.env.PLAYWRIGHT_CHROMIUM_PATH
  ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
  : {};
const browser = await chromium.launch(launchOpts);
try {
  for (const vp of viewports) {
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      isMobile: vp.isMobile,
      hasTouch: vp.isMobile,
    });
    const page = await context.newPage();
    const consoleErrors = [];
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));

    await page.goto(url, { waitUntil: 'load' });
    // Mobile starts with several sections collapsed; open them all as a user would.
    const defaults = await page.evaluate(() => ({
      open: [...document.querySelectorAll('details.sec')].filter((d) => d.open).map((d) => d.id),
      height: document.documentElement.scrollHeight,
      aboutOpen: [...document.querySelectorAll('.mc details.metric-details[open]')].length,
    }));
    await page.evaluate(() => document.querySelectorAll('details.sec').forEach((d) => { d.open = true; }));
    await page.waitForFunction((ids) => ids.every((id) => {
      const el = document.getElementById(id);
      return !!el && (!!el.querySelector('.main-svg') || el.textContent.includes('unavailable'));
    }), CHART_IDS, { timeout: 60000 });

    const tag = `[${vp.label}]`;
    const state = await page.evaluate((ids) => {
      const panel = document.querySelector('.fp-panel');
      const txt = (el) => (el ? el.textContent.trim() : null);
      const panelInfo = (id) => {
        const el = document.getElementById(id);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        const traces = (el.data || []).map((t) => ({
          name: t.name,
          points: (t.x || []).length,
          finite: (t.y || []).filter((v) => typeof v === 'number' && isFinite(v)).length,
        }));
        return {
          hasChart: !!el.querySelector('.main-svg'),
          width: r.width, height: r.height,
          traces,
          drawn: el.querySelectorAll('.scatterlayer .trace path.js-line, .scatterlayer .points path, .barlayer .point path').length,
          lastDate: (el.data && el.data[0] && el.data[0].x && el.data[0].x.length)
            ? el.data[0].x[el.data[0].x.length - 1] : null,
          xTicks: [...el.querySelectorAll('.xtick text')].map((t) => t.textContent).slice(0, 4),
          yTicks: [...el.querySelectorAll('.ytick text')].map((t) => t.textContent).slice(0, 4),
          annotations: [...el.querySelectorAll('.annotation text')].map((t) => t.textContent),
        };
      };
      const cards = [...panel.querySelectorAll('.fp-card')].map((c) => ({
        leg: c.dataset.leg,
        title: txt(c.querySelector('.fp-card-title')),
        value: txt(c.querySelector('[data-fp-value]')),
        chip: txt(c.querySelector('.fp-chip')),
        rows: [...c.querySelectorAll('.fp-row')].map((r) => r.lastElementChild.textContent.trim()),
        rule: txt(c.querySelector('.fp-rule')),
        stamp: txt(c.querySelector('.fast-stamp')),
      }));
      return {
        hasPanel: !!panel,
        score: txt(panel.querySelector('.fp-score b')),
        summary: txt(panel.querySelector('.fp-summary')),
        interp: txt(panel.querySelector('.fp-interp')),
        freshness: txt(panel.querySelector('.fp-freshness')),
        overlayNote: txt(panel.querySelector('.fp-overlay-note')),
        pathNodes: [...panel.querySelectorAll('.fp-node .fp-node-name')].map((n) => n.textContent.trim()),
        arrows: panel.querySelectorAll('.fp-arrow').length,
        pathCaption: txt(panel.querySelector('.fp-path-caption')),
        detailsCount: panel.querySelectorAll('details').length,
        cards,
        panels: Object.fromEntries(ids.map((id) => [id, panelInfo(id)])),
        rangeButtons: [...document.querySelectorAll('.sofr-range')].map((b) => b.dataset.range),
        docOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        panelOverflow: panel.scrollWidth - panel.clientWidth,
        legacyPanels: document.querySelectorAll('.sofr-panel').length,
        legacyKpis: document.querySelectorAll('.sofr-kpi').length,
        singleStockGex: /GEX Monitor|FlashAlpha|NVDA net GEX/i.test(document.body.innerText) || !!document.getElementById('chart-gex-nvda'),
      };
    }, CHART_IDS);

    // ---- Section structure -------------------------------------------------
    check(`${tag} no single-stock GEX monitor remains`, !state.singleStockGex);
    check(`${tag} unified funding-pressure panel present`, state.hasPanel);
    check(`${tag} resonance score and x/3 summary rendered`,
      /^[0-3]$/.test(state.score || '') && /\/\s*3 conditions active/.test(state.summary || ''),
      `${state.score} · ${state.summary}`);
    check(`${tag} interpretation + observation freshness in header`,
      (state.interp || '').length > 20 && /Observations:/.test(state.freshness || ''),
      (state.freshness || '').slice(0, 90));
    check(`${tag} strategy-overlay wording displayed`,
      /strategy overlay/i.test(state.overlayNote || ''), (state.overlayNote || '').slice(0, 60));
    check(`${tag} no duplicate standalone SOFR panel`, state.legacyPanels === 1 && state.legacyKpis === 0,
      `sofr-panel=${state.legacyPanels} sofr-kpi=${state.legacyKpis}`);

    // ---- Three signal cards with real values ------------------------------
    check(`${tag} three signal cards (sofr, reserves, tga)`,
      state.cards.length === 3 && ['sofr', 'reserves', 'tga'].every((l) => state.cards.some((c) => c.leg === l)),
      state.cards.map((c) => c.leg).join(','));
    for (const card of state.cards) {
      const numeric = /-?\d+(\.\d+)?/.test(card.value || '');
      check(`${tag} card ${card.leg} shows a real value`, numeric && card.value !== '\u2014', card.value);
      check(`${tag} card ${card.leg} shows a state word`, !!card.chip && card.chip.length > 2, card.chip);
      check(`${tag} card ${card.leg} shows two change rows + speed/median`,
        card.rows.length >= 3 && card.rows.every((r) => r && r !== '\u2014'), card.rows.join(' | '));
      check(`${tag} card ${card.leg} shows the explicit rule test`,
        /(met|not met|unavailable)/.test(card.rule || ''), (card.rule || '').slice(0, 90));
      check(`${tag} card ${card.leg} shows observation date + fetch time`,
        /observation \d{4}-\d{2}-\d{2}/.test(card.stamp || '') && /fetched/.test(card.stamp || ''),
        (card.stamp || '').slice(0, 90));
    }

    // ---- Pressure path ----------------------------------------------------
    check(`${tag} three-node pressure path with arrows`,
      state.pathNodes.length === 3 && state.arrows === 2, state.pathNodes.join(' -> '));
    check(`${tag} causality stated in words`,
      /drains bank reserves/i.test(state.pathCaption || '') && /above IORB/i.test(state.pathCaption || ''),
      (state.pathCaption || '').slice(0, 80));

    // ---- Three aligned chart panels ---------------------------------------
    for (const id of CHART_IDS) {
      const p = state.panels[id];
      check(`${tag} ${id} rendered`, !!p && p.hasChart);
      if (!p || !p.hasChart) continue;
      check(`${tag} ${id} has non-zero dimensions`, p.width > 200 && p.height > 100,
        `${Math.round(p.width)}x${Math.round(p.height)}`);
      const finite = Math.max(0, ...p.traces.map((t) => t.finite));
      check(`${tag} ${id} has finite data points`, finite > 20, String(finite));
      check(`${tag} ${id} draws series in the SVG`, p.drawn > 0, String(p.drawn));
      check(`${tag} ${id} axis labels present`, p.xTicks.length > 1 && p.yTicks.length > 1,
        `${p.xTicks.join('|')} / ${p.yTicks.join('|')}`);
    }
    const sofrPanel = state.panels['chart-sofr-iorb'];
    if (sofrPanel && sofrPanel.hasChart) {
      check(`${tag} SOFR panel keeps raw + filtered + calendar-noise series`,
        sofrPanel.traces.length === 3, sofrPanel.traces.map((t) => t.name).join(','));
      check(`${tag} +3bp strategy threshold labelled`,
        sofrPanel.annotations.some((a) => /\+3bp/.test(a)), sofrPanel.annotations.join(' / '));
      if (sofrPanel.lastDate) {
        const ageDays = Math.floor((Date.now() - Date.parse(sofrPanel.lastDate + 'T00:00:00Z')) / 86400000);
        // A source outage is acceptable only when the page says so: an old
        // observation must be labelled stale / last official observation.
        const staleLabelled = ageDays > MAX_STALE_DAYS && await page.evaluate(() =>
          /stale|last official observation/i.test((document.getElementById('funding-pressure') || {}).innerText || ''));
        check(`${tag} latest SOFR observation within ${MAX_STALE_DAYS} days or labelled stale`,
          ageDays <= MAX_STALE_DAYS || staleLabelled,
          `${sofrPanel.lastDate} (${ageDays}d old${staleLabelled ? ', labelled stale' : ''})`);
      } else {
        check(`${tag} latest SOFR observation available`, false, 'no series data');
      }
    }
    const resPanel = state.panels['chart-fp-reserves'];
    if (resPanel && resPanel.hasChart) {
      check(`${tag} reserves panel labels $2.90T and $2.80T references`,
        resPanel.annotations.some((a) => /2\.90T/.test(a)) && resPanel.annotations.some((a) => /2\.80T/.test(a)),
        resPanel.annotations.join(' / '));
      check(`${tag} reserves panel shows a 4-week slope cue`,
        resPanel.traces.some((t) => /slope/i.test(t.name || '')) ||
        resPanel.annotations.some((a) => /slope/i.test(a)),
        resPanel.traces.map((t) => t.name).join(','));
    }
    const tgaPanel = state.panels['chart-fp-tga'];
    if (tgaPanel && tgaPanel.hasChart) {
      check(`${tag} TGA panel labels $0.90T and $1.00T thresholds`,
        tgaPanel.annotations.some((a) => /0\.90T/.test(a)) && tgaPanel.annotations.some((a) => /1\.00T/.test(a)),
        tgaPanel.annotations.join(' / '));
      check(`${tag} TGA panel shows a 4-week slope cue`,
        tgaPanel.traces.some((t) => /slope/i.test(t.name || '')) ||
        tgaPanel.annotations.some((a) => /slope/i.test(a)),
        tgaPanel.traces.map((t) => t.name).join(','));
    }

    // ---- Range controls drive every panel ---------------------------------
    check(`${tag} 3M/6M/1Y/3Y controls present`,
      ['3M', '6M', '1Y', '3Y'].every((r) => state.rangeButtons.includes(r)),
      state.rangeButtons.join(','));
    const spans = {};
    for (const r of ['3M', '6M', '1Y', '3Y']) {
      await page.click(`.sofr-range[data-range="${r}"]`);
      await page.waitForFunction((range) => {
        const b = document.querySelector('.sofr-range.active');
        return b && b.dataset.range === range;
      }, r, { timeout: 5000 });
      const res = await page.evaluate((ids) => {
        const toMs = (v) => (typeof v === 'number' ? v : Date.parse(v));
        const out = {};
        for (const id of ids) {
          const el = document.getElementById(id);
          if (!el || !el._fullLayout) continue;
          const rg = el._fullLayout.xaxis.range.map(toMs);
          out[id] = rg[1] - rg[0];
        }
        return out;
      }, CHART_IDS);
      const rendered = Object.keys(res);
      const base = res[rendered[0]];
      spans[r] = base;
      check(`${tag} ${r} applies the same range to all rendered panels`,
        rendered.length === CHART_IDS.length && rendered.every((id) => res[id] > 0 && Math.abs(res[id] - base) < 864e5),
        rendered.map((id) => `${id}=${Math.round(res[id] / 864e5)}d`).join(' '));
    }
    check(`${tag} ranges are ordered 3M < 6M < 1Y < 3Y`,
      spans['3M'] < spans['6M'] && spans['6M'] < spans['1Y'] && spans['1Y'] < spans['3Y'],
      Object.entries(spans).map(([k, v]) => `${k}=${Math.round(v / 864e5)}d`).join(' '));

    // ---- Tooltip still carries real numbers -------------------------------
    await page.click('.sofr-range[data-range="6M"]');
    const box = await page.locator('#chart-sofr-iorb .nsewdrag').boundingBox();
    await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
    await page.waitForTimeout(400);
    const hover = await page.evaluate(() =>
      [...document.querySelectorAll('#chart-sofr-iorb .hoverlayer text')].map((t) => t.textContent).join(' | '));
    check(`${tag} tooltip shows numeric bp values`, /-?\d+(\.\d+)?\s*bp/.test(hover), hover.slice(0, 160));

    // ---- v2 FRED modules ----------------------------------------------------
    const v2 = await page.evaluate(() => {
      const secs = ['section-fed-bs', 'section-credit', 'section-rates'].map((t) => !!document.querySelector(`[data-testid="${t}"]`));
      const cards = ['mc-oas-ccc', 'mc-ccc-bb', 'mc-dgs30', 'mc-tp10', 'mc-fima', 'mc-wshobl', 'mc-sofr-disp']
        .map((t) => !!document.querySelector(`[data-testid="${t}"]`));
      const visible = [...document.querySelectorAll('.mfd-chart')].filter((el) => el.offsetParent !== null && el.clientWidth > 0);
      const drawn = visible.filter((el) => el.querySelector('svg.main-svg'));
      return { secs, cards, visible: visible.length, drawn: drawn.length };
    });
    check(`${tag} fed balance sheet, credit and rates sections present`, v2.secs.every(Boolean), JSON.stringify(v2.secs));
    check(`${tag} key v2 cards present`, v2.cards.every(Boolean), JSON.stringify(v2.cards));
    check(`${tag} visible v2 charts are drawn`, v2.visible >= 4 && v2.drawn === v2.visible, `${v2.drawn}/${v2.visible}`);
    await page.evaluate(() => document.querySelectorAll('details').forEach((d) => { d.open = true; }));
    await page.waitForTimeout(800);
    const widths = await page.evaluate(() => [...document.querySelectorAll('.mfd-chart')].map((el) => el.clientWidth));
    check(`${tag} all v2 charts have width after opening details`, widths.length >= 8 && widths.every((w) => w > 0), widths.join(','));

    // ---- Phase 5 layout ---------------------------------------------------
    const lay = await page.evaluate(() => ({
      tiles: document.querySelectorAll('[data-testid="scorecard"] .score').length,
      wc: !!document.querySelector('[data-testid="what-changed"]'),
      navLinks: document.querySelectorAll('.sec-nav a').length,
      chip: (document.querySelector('[data-testid="health-chip"]') || {}).textContent || '',
      takeaway: document.querySelectorAll('.takeaway-body li').length,
      layers: document.querySelectorAll('.layer-header').length,
      tailFolded: !!document.querySelector('details.fp-expand:not([open])') || !!document.querySelector('details.fp-expand'),
      oldStrip: !!document.querySelector('.summary-strip'),
      stateScript: !!document.getElementById('dash-state'),
    }));
    check(`${tag} scorecard has six tiles`, lay.tiles === 6, String(lay.tiles));
    check(`${tag} what-changed panel present`, lay.wc);
    check(`${tag} sticky navigation has eleven links`, lay.navLinks === 11, String(lay.navLinks));
    check(`${tag} health chip shows source counts`, /Sources \d+\/\d+/.test(lay.chip), lay.chip);
    check(`${tag} takeaway has four numbered points`, lay.takeaway === 4, String(lay.takeaway));
    check(`${tag} four layer headers`, lay.layers === 4, String(lay.layers));
    check(`${tag} old summary strip removed`, !lay.oldStrip);
    check(`${tag} daily state snapshot embedded`, lay.stateScript);
    if (vp.label === 'mobile') {
      check(`${tag} default open section on mobile is the LPI gauge only`, defaults.open.join(',') === 'sec-lpi', defaults.open.join(','));
      check(`${tag} default page height under 9000px`, defaults.height < 9000, String(defaults.height));
    } else {
      check(`${tag} all sections open by default`, defaults.open.length === 9, String(defaults.open.length));
    }
    // SOFR minus IORB monitor: always visible in the overview, drawn as a line chart, range-controlled
    const hero = await page.evaluate(async () => {
      const el = document.getElementById('chart-sofr-hero');
      const box = document.querySelector('[data-testid="sofr-hero"]');
      if (!el || !box) return { present: false };
      const out = { present: true, drawn: !!el.querySelector('.main-svg'), width: el.clientWidth,
        text: box.textContent, lines: (el.data || []).map((t) => t.mode + ':' + t.name), visibleTop: box.getBoundingClientRect().top + window.pageYOffset };
      const span = () => { const r = el._fullLayout.xaxis.range; return Math.round((new Date(r[1]) - new Date(r[0])) / 86400000); };
      const spans = {};
      for (const d of ['92', '365', '0']) {
        document.querySelector(`.sofr-hero-range[data-days="${d}"]`).click();
        await new Promise((r) => setTimeout(r, 400));
        spans[d] = span();
      }
      out.spans = spans;
      return out;
    });
    check(`${tag} SOFR-IORB monitor present in overview`, hero.present && hero.drawn && hero.width > 200, JSON.stringify({ w: hero.width }));
    check(`${tag} SOFR-IORB monitor is a line chart with raw and 5d median`, hero.present && hero.lines.length >= 2 && hero.lines.every((l) => l.startsWith('lines:')), (hero.lines || []).join(','));
    check(`${tag} SOFR-IORB monitor shows latest, median and rule`, hero.present && /Latest/.test(hero.text) && /5d median/.test(hero.text) && /Strategy rule/.test(hero.text) && /[+-]\d+\.\d bp/.test(hero.text));
    check(`${tag} SOFR-IORB range buttons change the window`, hero.present && hero.spans['92'] < hero.spans['365'] && hero.spans['365'] < hero.spans['0'], JSON.stringify(hero.spans));
    check(`${tag} SOFR-IORB monitor sits above the first layer`, hero.present && hero.visibleTop < 1500, String(Math.round(hero.visibleTop)));
    // Chart-first metric cards: every live card carries its own drawn time series, text sits behind About
    const mcs = await page.evaluate(() => {
      const cards = [...document.querySelectorAll('.mc')];
      const live = cards.filter((c) => !/not rendered as a current reading|No data this run/.test(c.textContent));
      const srf = document.querySelector('[data-testid="mc-srf"]');
      return {
        total: cards.length,
        noChart: live.filter((c) => !c.querySelector('.mc-chart')).map((c) => c.getAttribute('data-testid')),
        undrawn: live.filter((c) => { const ch = c.querySelector('.mc-chart'); return ch && (!ch.querySelector('.main-svg') || ch.clientWidth < 100); }).map((c) => c.getAttribute('data-testid')),
        shortChart: live.filter((c) => { const ch = c.querySelector('.mc-chart'); return ch && ch.clientHeight < 150; }).length,
        srfText: srf ? srf.querySelector('.mc-facts').textContent : '',
        srfValue: srf ? srf.querySelector('.mc-value').textContent : '',
        resGdp: !!document.querySelector('[data-testid="mcc-resgdp"] .main-svg'),
      };
    });
    check(`${tag} at least 30 metric cards`, mcs.total >= 30, String(mcs.total));
    check(`${tag} every live metric card has a chart`, mcs.noChart.length === 0, mcs.noChart.join(','));
    check(`${tag} every metric chart is drawn with width`, mcs.undrawn.length === 0, mcs.undrawn.join(','));
    check(`${tag} metric charts are at least 150px tall`, mcs.shortChart === 0, String(mcs.shortChart));
    check(`${tag} About text is collapsed by default`, defaults.aboutOpen === 0, String(defaults.aboutOpen));
    check(`${tag} standing repo card keeps value, floor and 3y percentile`, /\$[\d.]+B/.test(mcs.srfValue) && /floor/.test(mcs.srfText) && /p95/.test(mcs.srfText), mcs.srfValue + ' | ' + mcs.srfText);
    check(`${tag} reserves to GDP card has its chart`, mcs.resGdp);
    const calInfo = await page.evaluate(() => ({
      rows: document.querySelectorAll('[data-testid="cal-list"] li').length,
      text: document.getElementById('sec-calendar').textContent,
      drawn: !!document.getElementById('chart-stress-cal').querySelector('.main-svg'),
    }));
    check(`${tag} rolling calendar lists events with status labels`, calInfo.rows >= 6 && /announced|scheduled|estimated/.test(calInfo.text), String(calInfo.rows));
    check(`${tag} calendar has no hard-coded 2026 H2 percentiles`, !/H2|79th|2nd highest/.test(calInfo.text));
    check(`${tag} calendar chart drawn`, calInfo.drawn);
    // navigation: clicking a nav link opens and scrolls to the section
    await page.evaluate(() => document.querySelectorAll('details.sec').forEach((d) => { d.open = false; }));
    await page.click('.sec-nav a[data-target="sec-rates"]');
    await page.waitForTimeout(1500);
    const nav = await page.evaluate(() => {
      const d = document.getElementById('sec-rates');
      return { open: d.open, top: Math.round(d.getBoundingClientRect().top) };
    });
    check(`${tag} nav link opens and scrolls to the section`, nav.open && nav.top >= 0 && nav.top < 200, JSON.stringify(nav));
    // scorecard tile jumps to its section
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.click('[data-testid="score-credit"]');
    await page.waitForTimeout(500);
    check(`${tag} scorecard tile opens its section`, await page.evaluate(() => document.getElementById('sec-credit').open));
    // COT tabs
    await page.evaluate(() => document.getElementById('sec-crowding').open = true);
    const tabState = await page.evaluate(() => {
      const btns = [...document.querySelectorAll('.tabs[data-tabs="cot"] button')];
      if (btns.length < 2) return { n: btns.length };
      btns[1].click();
      const panes = [...document.querySelectorAll('.tab-pane[data-tabs="cot"]')];
      return { n: btns.length, visible: panes.map((p) => !p.hidden) };
    });
    check(`${tag} COT tabs switch panes`, tabState.n >= 2 && tabState.visible.filter(Boolean).length === 1 && tabState.visible[1] === true, JSON.stringify(tabState));
    await page.evaluate(() => document.querySelectorAll('details').forEach((d) => { d.open = false; }));

    // ---- Layout / hygiene -------------------------------------------------
    check(`${tag} no horizontal overflow`, state.docOverflow <= 1 && state.panelOverflow <= 1,
      `document=${state.docOverflow}px panel=${state.panelOverflow}px`);
    if (vp.isMobile) {
      const stacked = await page.evaluate(() => {
        const cards = [...document.querySelectorAll('.fp-card')];
        const tops = cards.map((c) => Math.round(c.getBoundingClientRect().top));
        const widest = Math.max(...cards.map((c) => c.getBoundingClientRect().width));
        return { unique: new Set(tops).size, count: cards.length, widest };
      });
      check('[mobile] signal cards stack vertically', stacked.unique === stacked.count,
        `${stacked.unique}/${stacked.count} distinct rows, widest ${Math.round(stacked.widest)}px`);
    }
    check(`${tag} expandable data description present`, state.detailsCount >= 4,
      String(state.detailsCount));
    check(`${tag} no console errors`, consoleErrors.length === 0, consoleErrors.join(' :: ').slice(0, 200));
    await context.close();
  }
} finally {
  await browser.close();
}

if (failures.length) {
  console.error(`\n${failures.length} browser check(s) failed:\n- ` + failures.join('\n- '));
  process.exit(1);
}
console.log('\nAll browser checks passed.');
