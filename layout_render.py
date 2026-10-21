"""Page-level layout pieces for v2: sticky navigation, overview scorecard, what-changed panel,
collapsible sections, COT heat strip, tabs and the data-health table."""
from __future__ import annotations

import html
from typing import Any

import fred_render as fr


def e(x: Any) -> str:
    return html.escape(str(x), quote=True)


CSS = (
    ".health-chip{display:inline-block;font-size:12px;border:1px solid var(--border);border-radius:999px;padding:3px 10px;color:var(--muted);background:var(--surface);cursor:pointer;text-decoration:none}"
    ".health-chip.ok{color:var(--ok);border-color:rgba(16,185,129,.4)}.health-chip.warn{color:var(--watch);border-color:rgba(245,158,11,.5)}.health-chip.bad{color:var(--stress);border-color:rgba(239,68,68,.5)}"
    ".sec-nav{position:sticky;top:0;z-index:60;display:flex;gap:6px;overflow-x:auto;padding:8px 20px;background:rgba(13,15,20,.94);border-bottom:1px solid var(--border);backdrop-filter:blur(6px);-webkit-overflow-scrolling:touch;scrollbar-width:none}"
    ".sec-nav::-webkit-scrollbar{display:none}"
    ".sec-nav a{flex:0 0 auto;color:var(--muted);text-decoration:none;font-size:12px;font-weight:600;padding:6px 10px;border-radius:6px;border:1px solid transparent;white-space:nowrap}"
    ".sec-nav a:hover{color:var(--text);background:#1e2433}.sec-nav a.active{color:#fff;background:var(--accent)}"
    ".overview{margin:14px 20px 4px}.overview h2,.what-changed h2{font-size:13px;font-weight:700;color:#cbd5e1;letter-spacing:.06em;text-transform:uppercase;margin:0 0 8px}"
    ".score-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}"
    ".score{display:block;text-decoration:none;background:var(--surface);border:1px solid var(--border);border-top:3px solid var(--na);border-radius:10px;padding:10px 12px;min-width:0;color:inherit}"
    ".score:hover{border-color:#475569}"
    ".score.st-normal{border-top-color:var(--ok)}.score.st-watch{border-top-color:var(--watch)}.score.st-elevated{border-top-color:var(--elev)}.score.st-stress{border-top-color:var(--stress)}"
    ".score-lbl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:700}"
    ".score-val{font-size:22px;font-weight:800;color:var(--text);margin-top:4px;line-height:1.1;font-variant-numeric:tabular-nums}"
    ".score.st-na .score-val,.score.st-context .score-val{color:var(--faint)}"
    ".score-row{display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:6px}"
    ".score-sub{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.4}"
    ".what-changed{margin:14px 20px 4px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px}"
    ".what-changed ul{margin:0;padding-left:18px;font-size:13px;color:#cbd5e1;line-height:1.65}"
    ".what-changed .wc-note{font-size:12px;color:var(--faint);margin-top:6px}"
    ".what-changed .up{color:var(--elev)}.what-changed .down{color:var(--ok)}"
    ".takeaway-body ol{margin:0;padding-left:20px}.takeaway-body li{margin-bottom:5px}"
    "details.sec{margin:0 20px 14px;border:1px solid var(--border);border-radius:12px;background:#10131a}"
    "details.sec>summary.sec-sum{cursor:pointer;list-style:none;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 16px;font-size:15px;font-weight:800;color:var(--text)}"
    "details.sec>summary.sec-sum::-webkit-details-marker{display:none}"
    "details.sec>summary.sec-sum::before{content:'\\25B8';color:var(--faint);margin-right:8px;transition:transform .15s}"
    "details.sec[open]>summary.sec-sum::before{transform:rotate(90deg)}"
    "details.sec>summary .sec-left{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 8px;flex:1}"
    "details.sec>summary .sec-zh{font-size:12px;font-weight:500;color:var(--faint)}"
    "details.sec>summary .sec-badge{flex:0 0 auto}"
    ".sec-body{padding:0 16px 14px}"
    ".sec-body .lpi-section,.sec-body .cot-section,.sec-body .gex-section{margin:0}"
    ".sec-body .fp-panel{margin:0 0 12px}"
    ".sec-body .mod-section{margin:0 0 12px}"
    ".heat{width:100%;max-width:760px;border-collapse:collapse;font-size:12px;margin:0 0 12px}"
    ".heat th{color:var(--muted);font-weight:600;text-align:right;padding:5px 8px;border-bottom:1px solid var(--border)}.heat th:first-child{text-align:left}"
    ".heat td{padding:6px 8px;text-align:right;border-bottom:1px solid #1e2433;font-variant-numeric:tabular-nums;color:#cbd5e1}.heat td:first-child{text-align:left;color:var(--text);font-weight:600}"
    ".heat td.pc{font-weight:700;color:#0d0f14}"
    ".heat tr.grp td{color:var(--faint);font-size:11px;text-transform:uppercase;letter-spacing:.05em;background:#0f1218;text-align:left}"
    ".tabs{display:flex;gap:6px;margin:0 0 10px;flex-wrap:wrap}"
    ".tabs button{background:#1e2433;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:12px;font-weight:600;cursor:pointer}"
    ".tabs button.active{background:var(--accent);color:#fff;border-color:var(--accent)}"
    ".tab-pane[hidden]{display:none}"
    ".health-table{width:100%;border-collapse:collapse;font-size:12px}"
    ".health-table th{color:var(--muted);text-align:left;font-weight:600;padding:5px 8px;border-bottom:1px solid var(--border)}"
    ".health-table td{padding:5px 8px;border-bottom:1px solid #1e2433;color:#cbd5e1}"
    ".health-table td.s-current{color:var(--ok)}.health-table td.s-cached{color:var(--watch)}.health-table td.s-stale,.health-table td.s-failed{color:var(--stress)}"
    ".cal-list{margin:0;padding:0;list-style:none;font-size:13px;color:#cbd5e1}"
    ".cal-list li{display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #1e2433}.cal-list .d{flex:0 0 96px;color:var(--text);font-variant-numeric:tabular-nums}"
    ".cal-list .k{flex:0 0 auto;font-size:11px;border-radius:4px;padding:2px 6px;background:#1e2433;color:var(--muted);align-self:flex-start}"
    ".cal-list .k.announced{color:var(--ok)}.cal-list .k.estimated{color:var(--watch)}"
    "@media(max-width:1100px){.score-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}"
    "@media(max-width:640px){.score-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.overview,.what-changed{margin-left:12px;margin-right:12px}"
    "details.sec{margin-left:10px;margin-right:10px}.sec-body{padding:0 10px 12px}.sec-nav{padding:8px 10px}.score-val{font-size:20px}"
    ".layer-header{margin-left:12px;margin-right:12px}}"
)


def nav_html(items: list[tuple[str, str]]) -> str:
    return '<nav class="sec-nav" data-testid="sec-nav">' + "".join(
        '<a href="#{}" data-target="{}">{}</a>'.format(e(i), e(i), e(t)) for i, t in items) + "</nav>"


def health_chip_html(summary: dict[str, Any]) -> str:
    if summary["failed"] or summary["stale"]:
        cls = "bad" if summary["failed"] else "warn"
    elif summary["cached"]:
        cls = "warn"
    else:
        cls = "ok"
    return '<a class="health-chip {}" href="#sec-methods" data-testid="health-chip">{}</a>'.format(cls, e(summary["chip"]))


def scorecard_html(tiles: list[dict[str, Any]]) -> str:
    out = ['<div class="overview" id="overview"><h2>Overview 总览 <span style="text-transform:none;letter-spacing:0;font-weight:400;color:var(--faint)">six layers at a glance, click a tile to jump</span></h2><div class="score-grid" data-testid="scorecard">']
    for t in tiles:
        st = t["state"]
        out.append('<a class="score {cls}" href="#{target}" data-testid="score-{id}"><div class="score-lbl">{lbl}</div>'
                   '<div class="score-val">{val}</div><div class="score-row"><span class="mc-badge {cls}">{badge}</span>{spark}</div>'
                   '<div class="score-sub">{sub}</div></a>'.format(
                       cls=fr.STATE_CLASS.get(st, "st-na"), target=e(t["target"]), id=e(t["id"]), lbl=e(t["title"]),
                       val=e(t["value"]), badge=fr.STATE_WORD.get(st, "STALE"),
                       spark=fr.spark_svg(t.get("spark", []), st, 64, 22) if t.get("spark") else "", sub=e(t["sub"])))
    out.append("</div></div>")
    return "".join(out)


def changes_html(items: list[str], base_note: str) -> str:
    body = "".join("<li>{}</li>".format(i) for i in items) if items else "<li>No indicator changed state and no standardized weekly move exceeded z 1.5.</li>"
    return ('<div class="what-changed" data-testid="what-changed"><h2>What changed 本周变化</h2><ul>{}</ul>'
            '<div class="wc-note">{}</div></div>').format(body, e(base_note))


def sec_open(sec_id: str, title: str, zh: str, mobile: str = "open", badge: str = "", testid: str = "") -> str:
    return ('<details class="sec" id="{id}" open data-mobile="{m}"{t}><summary class="sec-sum"><span class="sec-left">'
            '<span>{title}</span><span class="sec-zh">{zh}</span></span>{badge}</summary><div class="sec-body">').format(
        id=e(sec_id), m=mobile, title=title, zh=e(zh), badge=badge, t=' data-testid="{}"'.format(e(testid)) if testid else "")


def sec_close() -> str:
    return "</div></details>"


def state_badge(state: str, text: str | None = None) -> str:
    return '<span class="mc-badge sec-badge {}">{}</span>'.format(fr.STATE_CLASS.get(state, "st-na"), e(text or fr.STATE_WORD.get(state, "STALE")))


def heat_strip_html(rows: list[dict[str, Any]]) -> str:
    def color(p: float) -> str:
        if p != p:
            return "#334155"
        if p >= 90:
            return "#ef4444"
        if p >= 75:
            return "#f97316"
        if p <= 10:
            return "#38bdf8"
        if p <= 25:
            return "#7dd3fc"
        return "#475569"
    out = ['<table class="heat" data-testid="cot-heat"><thead><tr><th>Market</th><th>Net</th><th>Pctile</th><th>z (156w)</th><th>4w change</th></tr></thead><tbody>']
    last_grp = None
    for r in rows:
        if r["group"] != last_grp:
            out.append('<tr class="grp"><td colspan="5">{}</td></tr>'.format(e(r["group"])))
            last_grp = r["group"]
        p = r["pct"]
        out.append('<tr><td>{}</td><td>{}</td><td class="pc" style="background:{}">{}</td><td>{}</td><td>{}</td></tr>'.format(
            e(r["label"]), e(r["net"]), color(p), "n/a" if p != p else "{:.0f}".format(p), e(r["z"]), e(r["chg4"])))
    out.append("</tbody></table>")
    return "".join(out)


def tabs_html(tab_id: str, panes: list[tuple[str, str]], default: int = 0) -> str:
    """panes: [(label, inner html)]. Buttons and panes are linked by index."""
    btns = "".join('<button type="button" data-tabs="{t}" data-i="{i}"{a}>{l}</button>'.format(
        t=e(tab_id), i=i, a=' class="active"' if i == default else "", l=e(lbl)) for i, (lbl, _) in enumerate(panes))
    body = "".join('<div class="tab-pane" data-tabs="{t}" data-i="{i}"{h}>{c}</div>'.format(
        t=e(tab_id), i=i, h="" if i == default else " hidden", c=c) for i, (_, c) in enumerate(panes))
    return '<div class="tabs" data-tabs="{}">{}</div>{}'.format(e(tab_id), btns, body)


def health_table_html(entries: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    rows = "".join('<tr><td>{}</td><td>{}</td><td>{}</td><td class="s-{}">{}</td><td>{}</td></tr>'.format(
        e(x["name"]), e(x["source"]), e(x["observation_date"] or "none"), e(x["status"]), e(x["status"]), e(x["cadence"]))
        for x in entries)
    return ('<div class="mod-note">{}. Status compares each source with its own update cadence. Cached means the live request failed and the last official file was used.</div>'
            '<div style="overflow-x:auto"><table class="health-table" data-testid="health-table"><thead><tr><th>Source</th><th>Provider</th><th>Last observation</th>'
            '<th>Status</th><th>Cadence</th></tr></thead><tbody>{}</tbody></table></div>').format(e(summary["chip"]), rows)


JS = r"""
(function(){
  var links=[].slice.call(document.querySelectorAll('.sec-nav a'));
  function openFor(id){var el=document.getElementById(id);if(!el)return;var d=el.tagName==='DETAILS'?el:el.closest('details.sec');if(d&&!d.open)d.open=true;}
  links.forEach(function(a){a.addEventListener('click',function(ev){
    var id=a.getAttribute('data-target');var el=document.getElementById(id);if(!el)return;ev.preventDefault();
    openFor(id);var nav=document.querySelector('.sec-nav');var off=(nav?nav.offsetHeight:0)+6;
    var y=el.getBoundingClientRect().top+window.pageYOffset-off;window.scrollTo({top:y,behavior:'smooth'});});});
  document.querySelectorAll('.score').forEach(function(a){a.addEventListener('click',function(){var id=(a.getAttribute('href')||'').slice(1);openFor(id);});});
  if('IntersectionObserver' in window){
    var map={};links.forEach(function(a){map[a.getAttribute('data-target')]=a;});
    var io=new IntersectionObserver(function(es){es.forEach(function(en){if(en.isIntersecting){links.forEach(function(a){a.classList.remove('active');});
      var a=map[en.target.id];if(a)a.classList.add('active');}});},{rootMargin:'-20% 0px -70% 0px'});
    Object.keys(map).forEach(function(id){var el=document.getElementById(id);if(el)io.observe(el);});}
  document.querySelectorAll('.tabs button').forEach(function(b){b.addEventListener('click',function(){
    var t=b.getAttribute('data-tabs'),i=b.getAttribute('data-i');
    document.querySelectorAll('.tabs[data-tabs="'+t+'"] button').forEach(function(x){x.classList.toggle('active',x===b);});
    document.querySelectorAll('.tab-pane[data-tabs="'+t+'"]').forEach(function(p){var on=p.getAttribute('data-i')===i;p.hidden=!on;
      if(on&&typeof Plotly!=='undefined'){p.querySelectorAll('.js-plotly-plot').forEach(function(el){Plotly.Plots.resize(el);});}});});});
  document.addEventListener('toggle',function(ev){var d=ev.target;if(!d||!d.querySelectorAll||!d.open||typeof Plotly==='undefined')return;
    d.querySelectorAll('.js-plotly-plot').forEach(function(el){Plotly.Plots.resize(el);});},true);
  if(window.matchMedia&&window.matchMedia('(max-width:640px)').matches){
    document.querySelectorAll('details.sec[data-mobile="closed"]').forEach(function(d){d.open=false;});}
})();
"""
