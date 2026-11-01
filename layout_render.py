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
    ".chain-banner{display:flex;gap:14px;align-items:flex-start;background:var(--surface);border:1px solid var(--border);border-left:5px solid var(--na);border-radius:10px;padding:12px 14px;margin-bottom:10px}"
    ".chain-banner.st-normal{border-left-color:var(--ok)}.chain-banner.st-watch{border-left-color:var(--watch)}.chain-banner.st-elevated{border-left-color:var(--elev)}.chain-banner.st-stress{border-left-color:var(--stress)}"
    ".cb-lvl{flex:0 0 auto;min-width:120px}.cb-k{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:700}"
    ".cb-lvl b{display:block;font-size:26px;font-weight:800;line-height:1.15;margin-top:2px}.chain-banner.st-normal .cb-lvl b{color:var(--ok)}.chain-banner.st-watch .cb-lvl b{color:var(--watch)}.chain-banner.st-elevated .cb-lvl b{color:var(--elev)}.chain-banner.st-stress .cb-lvl b{color:var(--stress)}.chain-banner.st-na .cb-lvl b{color:var(--faint)}"
    ".cb-body{flex:1 1 auto;min-width:0;font-size:14px;line-height:1.55;color:var(--text)}.cb-why{font-weight:600}.cb-next{color:#cbd5e1;margin-top:4px}.cb-note{color:var(--watch);margin-top:4px}"
    ".chain-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}"
    ".stage{display:block;position:relative;text-decoration:none;color:inherit;background:var(--surface);border:1px solid var(--border);border-top:4px solid var(--na);border-radius:10px;padding:10px 12px;min-width:0}"
    ".stage:hover{border-color:#475569}.stage.cs-confirmed{border-top-color:var(--elev)}.stage.cs-partial{border-top-color:var(--watch)}.stage.cs-quiet{border-top-color:var(--ok)}"
    ".stage-top{display:flex;gap:8px;align-items:baseline}.stage-num{font-size:12px;font-weight:800;color:var(--muted);border:1px solid var(--border);border-radius:999px;padding:1px 7px}"
    ".stage-title{font-size:15px;font-weight:800;color:var(--text)}.stage-title .zh{font-weight:600;color:var(--muted);margin-left:6px;font-size:13px}"
    ".stage-q{font-size:12px;color:var(--muted);margin-top:4px;line-height:1.4}"
    ".stage-st{display:flex;gap:8px;align-items:center;margin-top:8px}.stage-n{font-size:12px;color:var(--muted)}"
    ".mc-badge.cs-confirmed{color:var(--elev);background:rgba(249,115,22,.14)}.mc-badge.cs-partial{color:var(--watch);background:rgba(245,158,11,.12)}.mc-badge.cs-quiet{color:var(--ok);background:rgba(16,185,129,.12)}"
    ".stage-inds{list-style:none;margin:8px 0 0;padding:0;font-size:12.5px;line-height:1.45}"
    ".stage-inds li{display:grid;grid-template-columns:10px minmax(0,1fr);column-gap:6px;padding:3px 0;border-top:1px solid rgba(148,163,184,.08)}"
    ".stage-inds li i{width:8px;height:8px;border-radius:50%;background:var(--na);margin-top:5px}.stage-inds li.on i{background:var(--elev)}.stage-inds li.off i{background:var(--ok)}"
    ".stage-inds li span{color:#cbd5e1}.stage-inds li b{grid-column:2;font-weight:700;color:var(--text);font-variant-numeric:tabular-nums}.stage-inds li.na span,.stage-inds li.na b{color:var(--faint)}"
    ".fsi-card{background:var(--surface);border:1px solid var(--border);border-left:5px solid var(--na);border-radius:10px;padding:12px 14px;margin-top:10px}"
    ".fsi-card.st-normal{border-left-color:var(--ok)}.fsi-card.st-watch{border-left-color:var(--watch)}.fsi-card.st-elevated{border-left-color:var(--elev)}.fsi-card.st-stress{border-left-color:var(--stress)}"
    ".fsi-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}.fsi-title{font-size:16px;font-weight:800;color:var(--text)}.fsi-title span{font-size:13px;color:var(--muted);font-weight:600;margin-left:6px}"
    ".fsi-sub{font-size:12.5px;color:var(--muted);margin-top:3px;line-height:1.45}.fsi-val{display:flex;gap:8px;align-items:center}.fsi-val b{font-size:30px;font-weight:800;color:var(--text);font-variant-numeric:tabular-nums}"
    ".fsi-card .mfd-chart{width:100%;height:280px;margin-top:6px}"
    ".fsi-comps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:8px}.fsi-comp{background:rgba(148,163,184,.06);border-radius:8px;padding:7px 9px;font-size:12.5px;color:#cbd5e1;line-height:1.4}.fsi-comp b{display:block;font-size:15px;color:var(--text)}"
    ".chain-log{margin-top:10px;font-size:13px;color:#cbd5e1;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 14px}.chain-log ul{margin:4px 0 0;padding-left:18px}.chain-log li{margin:2px 0}.chain-log .up{color:var(--elev)}.chain-log .down{color:var(--ok)}"
    "@media(max-width:1100px){.chain-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}"
    "@media(max-width:640px){.chain-grid{grid-template-columns:minmax(0,1fr)}.chain-banner{flex-direction:column;gap:6px}.cb-lvl b{font-size:24px}.cb-body{font-size:14px}"
    ".stage-inds{font-size:13px}.fsi-card .mfd-chart{height:300px}.fsi-comps{grid-template-columns:minmax(0,1fr)}.fsi-val b{font-size:26px}}"
    ".score-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}"
    ".score{display:block;text-decoration:none;background:var(--surface);border:1px solid var(--border);border-top:3px solid var(--na);border-radius:10px;padding:10px 12px;min-width:0;color:inherit}"
    ".score:hover{border-color:#475569}"
    ".score.st-normal{border-top-color:var(--ok)}.score.st-watch{border-top-color:var(--watch)}.score.st-elevated{border-top-color:var(--elev)}.score.st-stress{border-top-color:var(--stress)}"
    ".score-lbl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:700}"
    ".score-val{font-size:22px;font-weight:800;color:var(--text);margin-top:4px;line-height:1.1;font-variant-numeric:tabular-nums}"
    ".score.st-na .score-val,.score.st-context .score-val{color:var(--faint)}"
    ".score-row{display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:6px}"
    ".score-sub{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.4}"
    ".sofr-hero{margin:14px 20px 4px;background:var(--surface);border:1px solid var(--border);border-left:4px solid var(--accent);border-radius:12px;padding:12px 16px}"
    ".sh-head{display:flex;flex-wrap:wrap;gap:10px 22px;align-items:flex-start;justify-content:space-between}"
    ".sh-title{font-size:14px;font-weight:800;color:var(--text)}.sh-title span{font-size:12px;font-weight:500;color:var(--faint);margin-left:6px}"
    ".sh-sub{font-size:11px;color:var(--faint);margin-top:2px;max-width:520px}"
    ".sh-vals{display:flex;gap:22px;flex-wrap:wrap}.sh-vals b{display:block;font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--text)}"
    ".sh-vals b.sh-rule{font-size:14px;line-height:1.5}.sh-vals b.sh-rule.on{color:var(--elev)}.sh-vals b.sh-rule.near{color:var(--watch)}.sh-vals b.sh-rule.off{color:var(--ok)}"
    ".sh-where b{max-width:240px}"
    ".sh-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:700}"
    ".sh-ranges{display:flex;gap:6px}.sofr-hero-range{background:#1e2433;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:5px 10px;font-size:12px;font-weight:600;cursor:pointer}.sofr-hero-range.active{background:var(--accent);color:#fff;border-color:var(--accent)}"
    ".sofr-hero-chart{width:100%;margin-top:6px}.sh-note{font-size:11px;color:var(--faint);margin-top:6px;line-height:1.5}"
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
    "@media(max-width:640px){.score-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.overview,.what-changed,.sofr-hero{margin-left:12px;margin-right:12px}.sofr-hero{padding:10px 12px}"
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



CHAIN_TARGET = {"backdrop": "sec-lpi", "repo": "sofr-hero", "reserves": "sec-funding", "transmission": "sec-credit",
                "amplification": "sec-amplifiers"}
CHAIN_WORD = {"confirmed": "CONFIRMED", "partial": "PARTIAL", "quiet": "QUIET", "na": "NO DATA"}


def chain_html(chain: dict[str, Any], stance_en: str, stance_cn: str, note: str, fsi_block: str, log_items: list[str],
               log_note: str) -> str:
    """Overview: chain level banner, five stage tiles, the daily FSI card and the stage-change log."""
    lvl = chain["level"]
    why = "; ".join(chain["reasons"]) if chain["reasons"] else "no stage from 1 to 4 is confirmed"
    out = ['<div class="overview" id="overview"><h2>Overview 总览 <span style="text-transform:none;letter-spacing:0;font-weight:400;color:var(--faint)">'
           'fragility chain: pressure usually moves from repo to reserves to credit and rates, then to prices. Click a stage to open its section.</span></h2>',
           '<div class="chain-banner {cls}" data-testid="chain-level" data-level="{lvl}"><div class="cb-lvl"><span class="cb-k">Chain level 传导链等级</span><b>{word}</b></div>'
           '<div class="cb-body"><div class="cb-why">{stance} <span style="color:var(--muted);font-weight:500">({cn})</span></div>'
           '<div class="cb-next">Why: {why}. {nxt}</div>{note}</div></div>'.format(
               cls=fr.STATE_CLASS.get(lvl, "st-na"), lvl=e(lvl), word=fr.STATE_WORD.get(lvl, "NO DATA") if lvl != "na" else "NO DATA",
               stance=e(stance_en), cn=e(stance_cn), why=e(why), nxt=e(chain["next_watch"]),
               note=('<div class="cb-note" data-testid="chain-note">' + e(note) + '</div>') if note else ""),
           '<div class="chain-grid" data-testid="chain">']
    for st in chain["stages"]:
        lis = []
        for i in st["inds"]:
            cls = "na" if i["on"] is None else ("on" if i["on"] else "off")
            lis.append('<li class="{c}" title="{r}"><i></i><span>{n}</span><b>{v}</b></li>'.format(
                c=cls, r=e("On when: " + i["rule"]) if i["rule"] else "", n=e(i["name"]), v=e(i["value"])))
        hard = (' <span class="stage-n" style="color:var(--elev)">hard trigger: {}</span>'.format(e(st["hard_reason"]))
                if st.get("hard") and st.get("hard_reason") else "")
        out.append('<a class="stage cs-{s}" href="#{t}" data-testid="stage-{k}" data-status="{s}"><div class="stage-top">'
                   '<span class="stage-num">{num}</span><span class="stage-title">{ti}<span class="zh">{zh}</span></span></div>'
                   '<div class="stage-q">{q} {qz}</div><div class="stage-st"><span class="mc-badge cs-{s}">{w}</span>'
                   '<span class="stage-n">{n} of {a} on</span>{hard}</div><ul class="stage-inds">{lis}</ul></a>'.format(
                       s=e(st["status"]), t=CHAIN_TARGET.get(st["key"], "overview"), k=e(st["key"]), num=e(st["num"]),
                       ti=e(st["title"]), zh=e(st["title_zh"]), q=e(st["q"]), qz=e(st["q_zh"]), w=CHAIN_WORD.get(st["status"], "NO DATA"),
                       n=st["n_on"], a=st["n_avail"], hard=hard, lis="".join(lis)))
    out.append("</div>")
    out.append(fsi_block)
    body = "".join("<li>{}</li>".format(i) for i in log_items) if log_items else "<li>No chain stage, chain level or FSI band has changed since the record started.</li>"
    out.append('<div class="chain-log" data-testid="chain-log"><b>Stage changes 阶段变化记录</b><ul>{}</ul><div class="wc-note">{}</div></div>'.format(body, e(log_note)))
    out.append("</div>")
    return "".join(out)


def fsi_html(fsi: dict[str, Any], ranges: str) -> str:
    if not fsi.get("available"):
        return ('<div class="fsi-card st-na" data-testid="fsi"><div class="fsi-title">Funding stress index 资金压力指数</div>'
                '<div class="fsi-sub">Unavailable this run: fewer than two of the three funding prices had enough history.</div></div>')
    st = fsi.get("state", "na")
    rl, cl = fsi.get("raw_last", {}), fsi.get("comp_last", {})

    def comp(k, label, what):
        r, c = rl.get(k, float("nan")), cl.get(k, float("nan"))
        return ('<div class="fsi-comp">{l}<b>{r} &middot; p{c}</b>{w}</div>').format(
            l=e(label), r=("{:+.1f} bp".format(r) if r == r else "n/a"), c=("{:.0f}".format(c) if c == c else "n/a"), w=e(what))
    stale = " (stale)" if fsi.get("stale") else ""
    return ('<div class="fsi-card {cls}" data-testid="fsi"><div class="fsi-head"><div><div class="fsi-title">Funding stress index 资金压力指数<span>daily, 0 to 100</span></div>'
            '<div class="fsi-sub">Average of three funding prices, each ranked against its own history since 2018 (no look-ahead). As of {asof}{stale}; 20-day change {chg}.</div></div>'
            '<div class="fsi-val"><b>{v:.0f}</b><span class="mc-badge {cls}">{word}</span></div></div>{ranges}'
            '<div id="chart-fsi" class="mfd-chart" data-testid="chart-fsi"></div>'
            '<div class="fsi-comps">{c1}{c2}{c3}</div>'
            '<details class="metric-details"><summary>About this indicator 说明</summary><div>'
            'Repo: SOFR minus IORB, 5-observation median (collateral and dealer pressure). Interbank: EFFR minus IORB (reserve scarcity). '
            'Tail: SOFR 99th percentile minus the SOFR median, 5-observation median (how far the most expensive repo trades sit above the typical trade). '
            'Each spread is ranked against its trailing five years of daily data, using at least one year, with ties counted at their mid-rank so long flat periods sit near 50. '
            'IOER is used before IORB started on 2021-07-29. The index is the mean of the available ranks, with at least two required. '
            'Bands: below 60 normal, 60 to 80 watch, 80 to 95 elevated, 95 or more stress. '
            'In the backtest the index reached 100 in September 2019, 97 in March 2020 and 90 in October to November 2025; it stayed below 40 during the March 2023 bank failures, '
            'which were a deposit run rather than a funding-price event. It sits beside stages 1 and 2 and does not change the chain level by itself. '
            'Sources: NY Fed SOFR and SOFR percentiles, FRED EFFR, Federal Reserve IORB and IOER.</div></details></div>').format(
        cls=fr.STATE_CLASS.get(st, "st-na"), asof=e(fsi.get("asof", "n/a")), stale=stale,
        chg=("{:+.0f} points".format(fsi["chg20"]) if fsi.get("chg20") == fsi.get("chg20") else "n/a"),
        v=fsi["value"], word=fr.STATE_WORD.get(st, "STALE"), ranges=ranges,
        c1=comp("repo", "Repo: SOFR - IORB, 5d median", ""), c2=comp("interbank", "Interbank: EFFR - IORB", ""),
        c3=comp("tail", "Tail: SOFR 99th - median, 5d", ""))


def sofr_hero_html(latest: str, median: str, rule: str, rule_cls: str, obs: str, detail: str, since: str, available: bool,
                   effr: str = "n/a", where: str = "", where_cls: str = "off") -> str:
    btns = "".join('<button type="button" class="sofr-hero-range{}" data-days="{}">{}</button>'.format(
        " active" if lbl == "6M" else "", days, lbl) for lbl, days in (("3M", 92), ("6M", 183), ("1Y", 365), ("3Y", 1096), ("Max", 0)))
    body = ('<div id="chart-sofr-hero" class="sofr-hero-chart"></div>' if available else
            '<div class="mod-note">SOFR minus IORB is unavailable or stale this run; no current value is shown.</div>')
    return ('<div class="sofr-hero" id="sofr-hero" data-testid="sofr-hero"><div class="sh-head"><div><div class="sh-title">SOFR and EFFR minus IORB monitor <span>资金价格监测:回购与银行间</span></div>'
            '<div class="sh-sub">basis points, daily since {since} &middot; SOFR raw print, SOFR 5-observation median that skips calendar-noise days, and EFFR minus IORB for the interbank market</div></div>'
            '<div class="sh-vals"><div><span class="sh-lbl">SOFR latest</span><b>{latest}</b></div><div><span class="sh-lbl">SOFR 5d median</span><b>{median}</b></div>'
            '<div><span class="sh-lbl">Strategy rule</span><b class="sh-rule {rcls}">{rule}</b></div>'
            '<div><span class="sh-lbl">EFFR - IORB</span><b data-testid="hero-effr">{effr}</b></div>'
            '<div class="sh-where"><span class="sh-lbl">Where the pressure is</span><b class="sh-rule {wcls}" data-testid="hero-where">{where}</b></div></div>'
            '<div class="sh-ranges">{btns}</div></div>{body}'
            '<div class="sh-note">{obs} &middot; {detail}. SOFR is a secured repo rate (cash lent against Treasuries); EFFR is the unsecured rate banks pay each other for reserves. '
            'SOFR above IORB while EFFR stays below IORB points to collateral and dealer balance-sheet pressure; EFFR rising to IORB points to scarce reserves. '
            'The +3bp line is the operator strategy threshold, not an empirical law. Source: NY Fed SOFR, FRED EFFR and Federal Reserve IORB.</div></div>').format(
        since=e(since), latest=e(latest), median=e(median), rule=e(rule), rcls=e(rule_cls), btns=btns, body=body, obs=e(obs), detail=e(detail),
        effr=e(effr), where=e(where), wcls=e(where_cls))


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
  document.querySelectorAll('.score,.stage').forEach(function(a){a.addEventListener('click',function(){var id=(a.getAttribute('href')||'').slice(1);openFor(id);});});
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
