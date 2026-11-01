"""HTML, CSS and JS rendering for the v2 FRED modules.

Card anatomy (plan section 6.1): title, headline value, state badge, one-line description,
as-of line, expandable About block. Chart data is emitted as one JSON payload and drawn by a
small shared function, so every new chart has the same axes, reference lines, line-end labels
and 3M/6M/1Y/3Y/Max controls.
"""
from __future__ import annotations

import html
import json
from typing import Any

STATE_CLASS = {"normal": "st-normal", "watch": "st-watch", "elevated": "st-elevated",
               "stress": "st-stress", "na": "st-na", "context": "st-context"}
STATE_WORD = {"normal": "NORMAL", "watch": "WATCH", "elevated": "ELEVATED", "stress": "STRESS",
              "na": "STALE", "context": "CONTEXT"}

CSS = (
    ":root{--bg:#0d0f14;--surface:#141720;--border:#2d3748;--text:#e2e8f0;--muted:#94a3b8;--faint:#7c8aa0;"
    "--accent:#6366f1;--ok:#10b981;--watch:#f59e0b;--elev:#f97316;--stress:#ef4444;--na:#64748b}"
    ".mc-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0 0 12px}"
    ".mc-grid.cols-2{grid-template-columns:repeat(2,minmax(0,1fr))}.mc-grid.cols-4{grid-template-columns:repeat(4,minmax(0,1fr))}"
    ".mc{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--na);border-radius:10px;padding:14px;min-width:0}"
    ".mc.st-normal{border-left-color:var(--ok)}.mc.st-watch{border-left-color:var(--watch)}.mc.st-elevated{border-left-color:var(--elev)}"
    ".mc.st-stress{border-left-color:var(--stress)}.mc.st-na,.mc.st-context{border-left-color:var(--na)}"
    ".mc-top{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}"
    ".mc-title{font-size:12px;font-weight:700;color:#cbd5e1;letter-spacing:.03em;line-height:1.4}"
    ".mc-badge{font-size:11px;font-weight:700;border-radius:4px;padding:3px 6px;white-space:nowrap;background:rgba(100,116,139,.18);color:var(--muted)}"
    ".mc-badge.st-normal{color:var(--ok);background:rgba(16,185,129,.12)}.mc-badge.st-watch{color:var(--watch);background:rgba(245,158,11,.12)}"
    ".mc-badge.st-elevated{color:var(--elev);background:rgba(249,115,22,.12)}.mc-badge.st-stress{color:var(--stress);background:rgba(239,68,68,.14)}"
    ".mc-main{display:flex;align-items:flex-end;justify-content:space-between;gap:10px;margin-top:8px}"
    ".mc-value{font-size:24px;font-weight:700;color:var(--text);line-height:1.1;font-variant-numeric:tabular-nums}"
    ".mc.st-na .mc-value{color:var(--faint)}"
    ".mc-spark{flex:0 0 auto}.mc-spark svg{display:block}"
    ".mc-chart{width:100%;height:230px;margin-top:4px}"
    ".mc-chg{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums;margin-left:10px}.mc-chg.up{color:var(--elev)}.mc-chg.down{color:var(--ok)}.mc-chg.flat{color:var(--muted)}"
    ".mc-foot{border-top:1px solid #1e2433;margin-top:6px;padding-top:6px}"
    ".mc-facts{font-size:12px;color:var(--muted);margin-top:4px;line-height:1.45}"
    ".mc-nochart{font-size:12px;color:var(--faint);padding:14px 0}"
    ".mc-sub{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.45}"
    ".mc-what{font-size:12px;color:var(--faint);margin-top:6px;line-height:1.45}"
    ".mc-stamp{font-size:11px;color:var(--faint);margin-top:6px}"
    ".mc .metric-details{margin-top:8px}"
    ".mod-section{margin:0 0 18px}"
    ".mod-head{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:6px;margin:6px 0 8px}"
    ".mod-title{font-size:15px;font-weight:700;color:var(--text)}.mod-title span{font-size:12px;font-weight:400;color:var(--faint);margin-left:6px}"
    ".mod-intro{font-size:13px;color:var(--muted);line-height:1.55;margin:0 0 10px}"
    ".mod-sub{font-size:12px;font-weight:700;color:#cbd5e1;letter-spacing:.04em;text-transform:uppercase;margin:14px 0 8px}"
    ".mod-ranges{display:flex;gap:4px;flex-wrap:wrap}"
    ".mod-ranges button{background:#1e2433;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:4px 9px;font-size:12px;cursor:pointer}"
    ".mod-ranges button.active{background:var(--accent);color:#fff;border-color:var(--accent)}"
    ".mod-charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:0 0 12px}"
    ".mod-chart{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 12px 6px;min-width:0}"
    ".mod-chart .mfd-chart{width:100%;height:240px}"
    ".mod-note{font-size:12px;color:var(--faint);line-height:1.5;margin:6px 0 12px}"
    ".mod-note a,.mod-intro a{color:#a5b4fc}"
    ".where{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--na);border-radius:10px;padding:14px;margin:12px 0}"
    ".where.st-normal{border-left-color:var(--ok)}.where.st-watch{border-left-color:var(--watch)}.where.st-elevated{border-left-color:var(--elev)}.where.st-stress{border-left-color:var(--stress)}"
    ".where-verdict{font-size:20px;font-weight:700;color:var(--text);margin:6px 0 2px;line-height:1.3}.where-verdict span{display:block;font-size:14px;font-weight:600;color:var(--muted);margin-top:2px}"
    ".where-why{font-size:13px;color:var(--muted);line-height:1.5;margin:4px 0 8px}"
    ".where .mfd-chart{width:100%;height:300px}"
    ".where-tbl{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;margin-top:8px}"
    ".where-tbl th{white-space:nowrap;font-size:11px;color:var(--faint);font-weight:600;text-align:right;padding:4px 6px;border-bottom:1px solid #1e2433}"
    ".where-tbl th:first-child,.where-tbl td:first-child{text-align:left;white-space:normal}"
    ".where-tbl td{padding:5px 6px;text-align:right;white-space:nowrap;color:var(--text);border-bottom:1px solid #1e2433}"
    ".where-tbl tr.grp td{font-size:11px;color:var(--faint);text-transform:uppercase;letter-spacing:.05em;text-align:left;padding-top:8px}"
    ".where-tbl .sw{display:inline-block;width:10px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}"
    "@media(max-width:640px){.where .mfd-chart{height:320px}.where-verdict{font-size:18px}.where-tbl{font-size:12px}.where-tbl .hide-m{display:none}}"
    ".fast-status.context{color:#a5b4fc;background:rgba(99,102,241,.14)}"
    "@media(max-width:900px){.mc-grid,.mc-grid.cols-4{grid-template-columns:repeat(2,minmax(0,1fr))}.mod-charts{grid-template-columns:minmax(0,1fr)}}"
    "@media(max-width:640px){.mc-grid,.mc-grid.cols-2,.mc-grid.cols-4{grid-template-columns:minmax(0,1fr)}.mod-chart .mfd-chart{height:260px}.mc-value{font-size:22px}.mc{padding:11px 12px}.mc-chart{height:200px}}"
)


def e(text: Any) -> str:
    return html.escape(str(text), quote=True)


def spark_svg(values: list[float], state: str, w: int = 84, h: int = 26) -> str:
    vals = [v for v in values if v == v]
    if len(vals) < 3:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    pts = " ".join("{:.1f},{:.1f}".format(i * (w - 2) / (len(vals) - 1) + 1, h - 3 - (v - lo) / span * (h - 6)) for i, v in enumerate(vals))
    color = {"normal": "#10b981", "watch": "#f59e0b", "elevated": "#f97316", "stress": "#ef4444"}.get(state, "#64748b")
    return ('<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true"><polyline fill="none" stroke="{c}" '
            'stroke-width="1.6" stroke-linejoin="round" points="{p}"/></svg>').format(w=w, h=h, c=color, p=pts)


def src_name(url: str) -> str:
    return "NY Fed" if "newyorkfed" in url else "FRED"


def card_html(c: dict[str, Any]) -> str:
    st = c["state"]
    cls = STATE_CLASS.get(st, "st-na")
    stale = c.get("stale")
    badge = STATE_WORD.get(st, "STALE")
    if stale:
        sub = "Last observation {}; not rendered as a current reading.".format(e(c["asof"])) if c["value"] != "n/a" else "No data this run."
    else:
        sub = e(c["sub"])
    links = " · ".join('<a href="{}" target="_blank" rel="noopener">{} {}</a>'.format(e(u), src_name(u), e(i)) for i, u in c.get("links", []))
    det = []
    if c.get("what"):
        det.append("<b>Definition:</b> " + e(c["what"]))
    if c.get("why"):
        det.append("<b>Why it matters:</b> " + e(c["why"]))
    if c.get("rule"):
        det.append("<b>State rule:</b> " + e(c["rule"]))
    if c.get("unit_note"):
        det.append("<b>Units:</b> " + e(c["unit_note"]))
    if c.get("limits"):
        det.append("<b>Limitations:</b> " + e(c["limits"]))
    det.append("<b>Source:</b> " + links + (" · " + e(c["cadence"]) if c.get("cadence") else ""))
    if c.get("chart_id"):
        body = '<div id="{i}" class="mc-chart mfd-chart" data-testid="{i}"></div>'.format(i=e(c["chart_id"]))
    elif stale:
        body = ""
    else:
        body = '<div class="mc-nochart">No time series available for this indicator.</div>'
    return ('<div class="mc {cls}" data-testid="mc-{cid}"><div class="mc-top"><div class="mc-title">{title}</div>'
            '<span class="mc-badge {cls}">{badge}</span></div>'
            '<div class="mc-main"><div class="mc-value">{value}{chg}</div></div>'
            '{body}<div class="mc-foot"><div class="mc-facts">{sub}</div>'
            '<div class="mc-stamp">As of {asof}{cad}</div>'
            '<details class="metric-details"><summary>About this indicator 说明</summary><div>{det}</div></details></div></div>').format(
        cls=cls, cid=e(c["id"]), title=e(c["title"]), badge=badge, value=e(c["value"]), sub=sub, body=body, asof=e(c["asof"]),
        chg=('<span class="mc-chg {}" style="color:{}">{}</span>'.format(e(c["chg_dir"]), e(c.get("chg_color", "")), e(c["chg_txt"])) if c.get("chg_txt") and not stale else ""),
        cad=(" · " + e(c["cadence"].split(" (")[0])) if c.get("cadence") else "", det="<br>".join(det))


def grid_html(cards: list[dict[str, Any]], cols: int = 3) -> str:
    cls = "mc-grid" + (" cols-2" if cols == 2 else (" cols-4" if cols == 4 else ""))
    return '<div class="{}">'.format(cls) + "".join(card_html(c) for c in cards) + "</div>"


def chart_html(ch: dict[str, Any]) -> str:
    return ('<div class="mod-chart"><div class="chart-title">{t}</div><div class="chart-subtitle">{s}</div>'
            '<div id="{i}" class="mfd-chart" data-testid="{i}"></div></div>').format(t=e(ch["title"]), s=e(ch.get("subtitle", "")), i=e(ch["id"]))


def charts_html(charts: list[dict[str, Any]]) -> str:
    return '<div class="mod-charts">' + "".join(chart_html(c) for c in charts) + "</div>" if charts else ""


def ranges_html(sec: str, default: str = "1Y") -> str:
    btns = "".join('<button type="button" data-sec="{s}" data-range="{r}"{a}>{r}</button>'.format(
        s=sec, r=r, a=' class="active"' if r == default else "") for r in ("3M", "6M", "1Y", "3Y", "Max"))
    return '<div class="mod-ranges" data-sec="{}">{}</div>'.format(sec, btns)


def ranges_row(sec: str, default: str = "1Y") -> str:
    """Range buttons only; the section title lives in the collapsible section summary."""
    return '<div class="mod-head" style="justify-content:flex-end;margin-top:0">' + ranges_html(sec, default) + "</div>"


def section_head(title_en: str, title_zh: str, sec: str, default: str | None = "1Y") -> str:
    return ('<div class="mod-head"><div class="mod-title">{} <span>{}</span></div>{}</div>').format(
        e(title_en), e(title_zh), ranges_html(sec, default) if default else "")


def js_for(charts_by_section: dict[str, list[dict[str, Any]]]) -> str:
    """JS that draws every chart in the payload and wires the range buttons."""
    payload = json.dumps(charts_by_section, separators=(",", ":"))
    return r"""
var MFD=__PAYLOAD__;
var MFD_LAYOUT={paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",font:{color:"#94a3b8",size:12},
  margin:{l:46,r:56,t:8,b:36},hovermode:"x unified",autosize:true};
var MFD_RANGE_MONTHS={"3M":3,"6M":6,"1Y":12,"3Y":36};
function mfdFmt(v,unit){if(v===null||v===undefined||isNaN(v))return "";
  if(unit==="pct")return v.toFixed(2)+"%";if(unit==="bp")return Math.round(v).toLocaleString()+" bp";
  if(unit==="pp")return v.toFixed(2)+" pp";if(unit==="score")return Math.round(v)+"";if(unit==="gex")return (v>=0?"+":"")+v.toFixed(2)+"bn";if(unit==="ratio")return v.toFixed(3);if(unit==="price")return "$"+v.toFixed(2);if(unit==="x")return v.toFixed(2)+"x";if(unit==="$B")return "$"+(v<10?v.toFixed(1):Math.round(v).toLocaleString())+"B";if(unit==="$T")return "$"+v.toFixed(2)+"T";return v.toFixed(2);}
function mfdRangeFor(c,label){
  var last=null;c.traces.forEach(function(t){if(t.x.length){var d=t.x[t.x.length-1];if(!last||d>last)last=d;}});
  if(!last||label==="Max")return null;
  var d=new Date(last+"T00:00:00Z");d.setUTCMonth(d.getUTCMonth()-MFD_RANGE_MONTHS[label]);
  var first=null;c.traces.forEach(function(t){if(t.x.length&&(!first||t.x[0]<first))first=t.x[0];});
  if(first){var f=new Date(first+"T00:00:00Z");f.setUTCDate(f.getUTCDate()-2);if(f>d)d=f;}
  var end=new Date(last+"T00:00:00Z");end.setUTCDate(end.getUTCDate()+3);
  return [d.toISOString().slice(0,10),end.toISOString().slice(0,10)];}
function mfdDraw(c,label){
  var el=document.getElementById(c.id);if(!el||typeof Plotly==="undefined")return;
  var traces=c.traces.map(function(t){
    var o={x:t.x,y:t.y,name:t.name,hovertemplate:"%{y:,.2f}"};
    if(t.type==="bar"){o.type="bar";o.marker={color:t.colors||t.color};}
    else{o.type="scatter";o.mode="lines";o.line={color:t.color,width:t.width||(c.mini?2.6:2)};if(t.dash)o.line.dash=t.dash;if(c.stacked){o.stackgroup="one";o.fillcolor=t.color+"55";}}
    return o;});
  if(c.mini&&c.traces[0].type!=="bar"&&c.traces[0].x.length){var t0=c.traces[0],li=t0.x.length-1;
    traces.push({x:[t0.x[li]],y:[t0.y[li]],type:"scatter",mode:"markers",marker:{color:t0.color,size:8,line:{color:"#0d0f14",width:1.5}},showlegend:false,hoverinfo:"skip"});}
  var shapes=[],ann=[];
  (c.refs||[]).forEach(function(r){
    shapes.push({type:"line",xref:"paper",x0:0,x1:1,yref:"y",y0:r.y,y1:r.y,line:{color:r.color,width:1,dash:"dot"}});
    ann.push({xref:"paper",x:(c.traces[0].type==="bar"?0.99:0.01),xanchor:(c.traces[0].type==="bar"?"right":"left"),yref:"y",y:r.y,yanchor:"bottom",text:r.label,showarrow:false,font:{size:10,color:r.color}});});
  if(c.band){shapes.push({type:"rect",xref:"x",x0:c.band.x0,x1:c.band.x1,yref:"paper",y0:0,y1:1,fillcolor:"rgba(148,163,184,0.13)",line:{width:0},layer:"below"});
    ann.push({xref:"x",x:c.band.x0,xanchor:"right",yref:"paper",y:1,yanchor:"top",text:c.band.label,showarrow:false,font:{size:11,color:"#cbd5e1"},xshift:-3});}
  (c.vlines||[]).forEach(function(v){
    shapes.push({type:"line",xref:"x",x0:v.x,x1:v.x,yref:"paper",y0:0,y1:1,line:{color:"#a5b4fc",width:1,dash:"dash"}});
    ann.push({xref:"x",x:v.x,xanchor:"left",yref:"paper",y:1,yanchor:"top",text:v.label,showarrow:false,font:{size:10,color:"#a5b4fc"}});});
  if(!c.stacked&&c.traces.length<=3){c.traces.forEach(function(t){
    if(t.type==="bar"||!t.x.length||t.nolabel)return;
    ann.push({xref:"x",x:t.x[t.x.length-1],xanchor:"left",yref:"y",y:t.y[t.y.length-1],text:mfdFmt(t.y[t.y.length-1],c.unit),
      showarrow:false,font:{size:11,color:t.color},xshift:4});});}
  var lay=JSON.parse(JSON.stringify(MFD_LAYOUT));
  lay.shapes=shapes;lay.annotations=ann;lay.showlegend=c.traces.length>1;if(c.barmode)lay.barmode=c.barmode;
  lay.legend={orientation:"h",y:-0.22,font:{size:11}};if(lay.showlegend)lay.margin.b=58;
  if(c.mini){lay.margin={l:40,r:54,t:8,b:lay.showlegend?44:22};lay.legend={orientation:"h",y:-0.16,font:{size:10}};}
  lay.xaxis={gridcolor:"#1e2433",zerolinecolor:"#2d3748",tickfont:{size:11},nticks:5,fixedrange:true};
  lay.yaxis={gridcolor:"#1e2433",zerolinecolor:"#2d3748",tickfont:{size:11},automargin:true,fixedrange:true,
    ticksuffix:c.unit==="pct"?"%":""};
  var rng=mfdRangeFor(c,label||c.default_range||"1Y");if(rng){lay.xaxis.range=rng;}
  var ys=[];(c.refs||[]).forEach(function(r){ys.push(r.y);});
  Plotly.react(el,traces,lay,{responsive:true,displayModeBar:false});
  if(rng){var vis=[];c.traces.forEach(function(t){t.x.forEach(function(d,i){if(d>=rng[0]&&d<=rng[1]&&t.y[i]!==null)vis.push(t.y[i]);});});
    if(c.barmode==="relative"){var pos={},neg={};c.traces.forEach(function(t){if(t.type!=="bar")return;t.x.forEach(function(d,i){var v=t.y[i];if(v===null||d<rng[0]||d>rng[1])return;if(v>=0)pos[d]=(pos[d]||0)+v;else neg[d]=(neg[d]||0)+v;});});
      Object.keys(pos).forEach(function(k){vis.push(pos[k]);});Object.keys(neg).forEach(function(k){vis.push(neg[k]);});}
    if(vis.length){var all=vis.concat(ys.filter(function(y){var lo=Math.min.apply(null,vis),hi=Math.max.apply(null,vis);var pad=(hi-lo)*0.6||1;return y>=lo-pad&&y<=hi+pad;}));
      var lo=Math.min.apply(null,all),hi=Math.max.apply(null,all),pad=(hi-lo)*0.08||1;
      Plotly.relayout(el,{"yaxis.range":[(c.traces[0].type==="bar"&&lo>0)?0:lo-pad,hi+pad]});}}}
function mfdDrawSection(sec,label,init){(MFD[sec]||[]).forEach(function(c){mfdDraw(c,(init&&c.initial_range)||label);});}
Object.keys(MFD).forEach(function(sec){
  var first=(document.querySelector('.mod-ranges[data-sec="'+sec+'"] button.active')||{}).dataset;
  mfdDrawSection(sec,first&&first.range,true);});
document.querySelectorAll(".mod-ranges button").forEach(function(b){
  b.addEventListener("click",function(){
    var sec=b.dataset.sec;
    document.querySelectorAll('.mod-ranges[data-sec="'+sec+'"] button').forEach(function(x){x.classList.toggle("active",x===b);});
    mfdDrawSection(sec,b.dataset.range);});});
document.addEventListener("toggle",function(ev){var d=ev.target;if(!d||!d.querySelectorAll)return;
  d.querySelectorAll(".mfd-chart").forEach(function(el){if(typeof Plotly!=="undefined")Plotly.Plots.resize(el);});},true);
window.addEventListener("resize",function(){document.querySelectorAll(".mfd-chart").forEach(function(el){if(el.offsetParent&&typeof Plotly!=="undefined")Plotly.Plots.resize(el);});});
""".replace("__PAYLOAD__", payload)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------
def where_html(w: dict[str, Any]) -> str:
    """Secured vs unsecured diagnostic panel: verdict, five-line chart, then the spread table."""
    if not w:
        return ""
    st = w.get("state", "na")
    cls = STATE_CLASS.get(st, "st-na")

    def bp(v, signed=True):
        return "n/a" if v != v else ("{:+.0f} bp" if signed else "{:.0f} bp").format(v)

    rows = []
    for grp, flag in (("Secured repo 担保回购 (collateral: Treasuries)", True), ("Unsecured bank funding 无担保银行间", False)):
        rows.append('<tr class="grp"><td colspan="6">{}</td></tr>'.format(e(grp)))
        for r in w.get("rows", []):
            if r.get("secured", r["id"] in ("SOFR", "BGCR", "TGCRRATE")) != flag:
                continue
            if not r.get("available"):
                rows.append('<tr><td><span class="sw" style="background:{}"></span>{}</td><td colspan="5">n/a</td></tr>'.format(e(r["color"]), e(r["name"])))
                continue
            vol = "n/a" if r["vol"] != r["vol"] else "${:,.0f}B".format(r["vol"])
            rows.append(('<tr><td><span class="sw" style="background:{c}"></span>{n}</td><td>{rate:.2f}%</td><td><b>{bp}</b></td>'
                         '<td>{c5}</td><td class="hide-m">{c20}</td><td>{vol}</td></tr>').format(
                c=e(r["color"]), n=e(r["name"]), rate=r["rate"], bp=bp(r["bp"]), c5=bp(r["chg5"]), c20=bp(r["chg20"]), vol=vol))
    tbl = ('<table class="where-tbl" data-testid="where-table"><thead><tr><th>Rate 利率</th><th>Level</th><th>vs IORB</th><th>5d</th>'
           '<th class="hide-m">20d chg</th><th>Volume</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>")
    links = " · ".join('<a href="{}" target="_blank" rel="noopener">{} {}</a>'.format(e(u), src_name(u), e(i)) for i, u in w.get("links", []))
    chart = ""
    if w.get("chart"):
        chart = '<div id="{i}" class="mfd-chart" data-testid="{i}"></div>'.format(i=e(w["chart"]["id"]))
    det = ("<b>Why two markets:</b> SOFR, BGCR and TGCR are repo rates: cash lent overnight against Treasury collateral. They rise when "
           "dealers need cash to finance Treasury positions, when Treasury auctions settle, or when the TGA pulls cash out of money funds. "
           "EFFR and OBFR are unsecured loans between banks and FHLBs. They rise when banks are short of reserves. Repo can trade above IORB "
           "while banks still hold enough reserves; only when EFFR also climbs toward IORB is the shortage in reserves themselves."
           "<br><b>Classification rule:</b> " + e(w.get("rule", "")) +
           "<br><b>Scope:</b> descriptive. Outside the LPI, the funding resonance count and the de-lever tally."
           "<br><b>Source:</b> " + links + " · daily, prior business day")
    return ('<div class="where {cls}" data-testid="where-panel"><div class="mc-top"><div class="mc-title">Where is the funding pressure? '
            '资金压力在哪个市场</div><span class="mc-badge {cls}">{badge}</span></div>'
            '<div class="where-verdict" data-testid="where-verdict">{en}<span>{zh}</span></div>'
            '<div class="where-why">SOFR - IORB 5d median {sec} · EFFR - IORB {un} (20d {unc}). {why}</div>'
            '{chart}{tbl}<div class="mc-stamp">As of {asof}</div>'
            '<details class="metric-details"><summary>About this diagnostic 说明</summary><div>{det}</div></details></div>').format(
        cls=cls, badge=STATE_WORD.get(st, "STALE"), en=e(w.get("label_en", "")), zh=e(w.get("label_zh", "")),
        sec=bp(w.get("secured_med_bp", float("nan"))), un=bp(w.get("unsec_bp", float("nan"))), unc=bp(w.get("unsec_chg20_bp", float("nan"))),
        why=e(w.get("why", "")), chart=chart, tbl=tbl, asof=e(w.get("asof") or "unavailable"), det=det)


def backstops_html(f: dict[str, Any]) -> str:
    n, a = f["backstops_in_use"], f["backstops_avail"]
    dw = f.get("dw_state", "unavailable")
    head = ('<div class="mod-sub">Backstop facilities 后备工具 <span style="text-transform:none;letter-spacing:0;font-weight:400;color:var(--faint)">'
            'in use: {}/{} of SRF, swaps, FIMA repo · discount window: {}</span></div>').format(n, a, e(dw.replace("_", " ")))
    return head + ranges_row("funding", "1Y") + grid_html(f["backstops"], 3)


def funding_extras_html(f: dict[str, Any]) -> str:
    out = ['<div class="mod-sub">Repo and interbank spreads, dispersion &amp; volume 回购与银行间利差、分布与成交量</div>', grid_html(f["cards"], 3)]
    out.append('<details class="fp-expand"><summary>Show SOFR percentile band and volume charts</summary>')
    out.append('<div class="mod-sub">SOFR distribution SOFR 分布</div>')
    out.append(charts_html(f["charts"]))
    out.append("</details>")
    return "".join(out)


def fedbs_html(m: dict[str, Any]) -> str:
    by = {c["id"]: c for c in m["cards"]}
    top = [by[k] for k in ("netliq", "wresbal", "wtregen") if k in by]
    rmp = [by[k] for k in ("wshobl", "wshosho", "wsefintl1") if k in by]
    rest = [c for c in m["cards"] if c not in top and c not in rmp]
    out = ['<div class="mod-section" data-testid="section-fed-bs">',
           ranges_row("fedbs", "1Y"),
           '<div class="mod-sub">Net liquidity and its drivers 净流动性与驱动项</div>',
           '<p class="mod-intro">Net liquidity is Fed assets minus the Treasury General Account (TGA) minus overnight reverse repo (ON RRP). '
           'The bars split each week\u2019s change into those three items, so a drain can be traced to a TGA build, balance-sheet runoff or cash returning to ON RRP. '
           'Compare windows with the same end date: a 4-week change can flip sign when one large week enters or leaves the window.</p>',
           grid_html(top, 3), charts_html([m["netliq_chart"]] if m.get("netliq_chart") else []),
           '<div class="mod-sub">Reserve management purchases 准备金管理购买</div>',
           '<p class="mod-intro">Reserve management purchases (RMP) are purchases of short-dated Treasury bills that the Fed uses to keep reserves ample. '
           'They started on 2025-12-12 per the <a href="{}" target="_blank" rel="noopener">NY Fed statement</a>. This block is context, not a signal: no state is assigned.</p>'.format(e(m["rmp_url"])),
           grid_html(rmp, 3), charts_html(m["charts"]),
           '<details class="fp-expand"><summary>Show SOMA composition and Fed total assets</summary>']
    if m.get("comp_chart"):
        out.append(charts_html([m["comp_chart"]]))
    out.append(grid_html(rest, 3))
    out.append("</details></div>")
    return "".join(out)


def credit_html(m: dict[str, Any]) -> str:
    return "".join(['<div class="mod-section" data-testid="section-credit">',
                    ranges_row("credit", "1Y"),
                    '<p class="mod-intro">ICE BofA option-adjusted spreads by rating, the CCC minus BB quality spread, and official financial conditions indexes. '
                    'States compare each series with its own history and its 20-day change.</p>',
                    '<div class="mod-sub">Spread ladder 利差梯度</div>', grid_html(m["ladder"], 3),
                    '<div class="mod-sub">Quality spread &amp; conditions 质量利差与金融条件</div>', grid_html(m["cards"], 3),
                    charts_html([c for c in m["charts"] if not c.get("collapsed")]),
                    '<details class="fp-expand"><summary>Show CCC minus BB 20-day change</summary>',
                    charts_html([c for c in m["charts"] if c.get("collapsed")]), "</details></div>"])


def rates_html(m: dict[str, Any]) -> str:
    return "".join(['<div class="mod-section" data-testid="section-rates">',
                    ranges_row("rates", "1Y"),
                    '<p class="mod-intro">Read together with the LPI duration supply factor: issuance pressure and term premium usually move together. '
                    'Term premium is a model estimate. Reference lines are operator references, not statistical thresholds.</p>',
                    grid_html(m["cards"], 3), charts_html(m["charts"]), "</div>"])
