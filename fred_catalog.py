"""Catalog of FRED series used by the v2 funding, Fed balance sheet, credit and rates modules.

Data definitions only. Every entry was checked against the public fredgraph CSV endpoint
(see METHODOLOGY.md). Units are explicit: H.4.1 series (W...) are $ millions, H.8 is
$ billions, SOFRVOL is $ billions, rates and ICE BofA OAS are percent.

None of these series feed the LPI composite or the de-leveraging tally (decision D6).
"""
from __future__ import annotations

from dataclasses import dataclass

FRED_SERIES_URL = "https://fred.stlouisfed.org/series/{id}"

SECTIONS = ("funding", "backstop", "fedbs", "credit", "rates", "vol")


@dataclass(frozen=True)
class FredSpec:
    id: str
    label_en: str
    label_zh: str
    section: str
    unit_raw: str           # unit FRED publishes: percent | millions | billions | index | trillions
    display: str            # unit shown on the page: bp | pct | $B | $T | index
    scale: float            # display value = raw value * scale (percent -> bp uses 100)
    cadence: str
    max_age_days: int       # older than this is stale (grey, no status)
    start: str              # observation_start used for the fetch
    role: str = "context"   # state = drives a descriptive state label; context = plotted only

    @property
    def url(self) -> str:
        return FRED_SERIES_URL.format(id=self.id)


DAILY = "daily business day"
WEEKLY_H41 = "weekly (H.4.1, Wednesday level, Thursday release)"
WEEKLY_H8 = "weekly (H.8)"
WEEKLY_FRI = "weekly (Friday)"


def _s(*a, **k) -> FredSpec:
    return FredSpec(*a, **k)


CATALOG: tuple[FredSpec, ...] = (
    # ---- Funding and plumbing (4a) -------------------------------------------------
    _s("SOFR", "SOFR", "SOFR", "funding", "percent", "pct", 1.0, DAILY, 5, "2023-01-01"),
    _s("IORB", "IORB", "准备金利率 IORB", "funding", "percent", "pct", 1.0, DAILY, 10, "2023-01-01"),
    _s("TGCRRATE", "Tri-party general collateral rate", "三方回购利率 TGCR", "funding", "percent", "pct", 1.0, DAILY, 5, "2023-01-01", "state"),
    _s("SOFR1", "SOFR 1st percentile", "SOFR 第1分位", "funding", "percent", "pct", 1.0, DAILY, 5, "2023-01-01"),
    _s("SOFR25", "SOFR 25th percentile", "SOFR 第25分位", "funding", "percent", "pct", 1.0, DAILY, 5, "2023-01-01"),
    _s("SOFR75", "SOFR 75th percentile", "SOFR 第75分位", "funding", "percent", "pct", 1.0, DAILY, 5, "2023-01-01"),
    _s("SOFR99", "SOFR 99th percentile", "SOFR 第99分位", "funding", "percent", "pct", 1.0, DAILY, 5, "2023-01-01"),
    _s("SOFRVOL", "SOFR transaction volume", "SOFR 成交量", "funding", "billions", "$B", 1.0, DAILY, 5, "2023-01-01"),
    _s("RPONTSYD", "Standing repo / overnight repo (Treasury)", "SRF 隔夜回购", "backstop", "billions", "$B", 1.0, DAILY, 5, "2023-01-01", "state"),
    # ---- Backstops (H.4.1, $ millions) ------------------------------------------------
    _s("WLCFLPCL", "Discount window primary credit", "贴现窗口 primary credit", "backstop", "millions", "$B", 0.001, WEEKLY_H41, 12, "2020-01-01", "state"),
    _s("SWPT", "Central bank liquidity swaps", "央行流动性互换", "backstop", "millions", "$B", 0.001, WEEKLY_H41, 12, "2020-01-01", "state"),
    _s("H41RESPPALGTRFNWW", "FIMA repo facility (actual usage)", "FIMA 回购便利用量", "backstop", "millions", "$B", 0.001, WEEKLY_H41, 12, "2020-01-01", "state"),
    _s("WLRRAFOIAL", "Foreign official reverse repo pool (liability)", "外国官方逆回购池(负债)", "backstop", "millions", "$B", 0.001, WEEKLY_H41, 12, "2020-01-01"),
    # ---- Fed balance sheet and RMP (4b, H.4.1, $ millions) -------------------------------
    _s("WSHOBL", "SOMA Treasury bills", "SOMA 持有 T-bill", "fedbs", "millions", "$B", 0.001, WEEKLY_H41, 12, "2023-01-01"),
    _s("WSHOSHO", "SOMA securities held outright", "SOMA 持有证券总额", "fedbs", "millions", "$T", 1e-6, WEEKLY_H41, 12, "2023-01-01"),
    _s("WSHONBNL", "SOMA Treasury notes and bonds (nominal)", "SOMA 中长期国债", "fedbs", "millions", "$B", 0.001, WEEKLY_H41, 12, "2023-01-01"),
    _s("WSHOMCB", "SOMA mortgage-backed securities", "SOMA MBS", "fedbs", "millions", "$B", 0.001, WEEKLY_H41, 12, "2023-01-01"),
    _s("WSEFINTL1", "Securities held in custody for foreign official accounts", "外国官方托管证券", "fedbs", "millions", "$T", 1e-6, WEEKLY_H41, 12, "2023-01-01"),
    _s("WALCL", "Fed total assets", "美联储总资产", "fedbs", "millions", "$T", 1e-6, WEEKLY_H41, 12, "2023-01-01"),
    _s("WRESBAL", "Reserve balances at Federal Reserve Banks", "准备金余额", "fedbs", "millions", "$T", 1e-6, WEEKLY_H41, 12, "2023-01-01"),
    _s("WTREGEN", "Treasury General Account", "财政部 TGA", "fedbs", "millions", "$T", 1e-6, WEEKLY_H41, 12, "2023-01-01"),
    # ---- Credit (4c) ---------------------------------------------------------------
    _s("BAMLH0A0HYM2", "US high yield OAS", "美国高收益债 OAS", "credit", "percent", "bp", 100.0, DAILY, 5, "2023-01-01", "state"),
    _s("BAMLC0A0CM", "US investment grade OAS", "美国投资级 OAS", "credit", "percent", "bp", 100.0, DAILY, 5, "2023-01-01", "state"),
    _s("BAMLC0A4CBBB", "US BBB OAS", "BBB OAS", "credit", "percent", "bp", 100.0, DAILY, 5, "2023-01-01", "state"),
    _s("BAMLH0A1HYBB", "BB OAS", "BB OAS", "credit", "percent", "bp", 100.0, DAILY, 5, "2023-01-01", "state"),
    _s("BAMLH0A2HYB", "Single-B OAS", "B OAS", "credit", "percent", "bp", 100.0, DAILY, 5, "2023-01-01", "state"),
    _s("BAMLH0A3HYC", "CCC and lower OAS", "CCC及以下 OAS", "credit", "percent", "bp", 100.0, DAILY, 5, "2023-01-01", "state"),
    _s("BAMLEMCBPIOAS", "Emerging markets corporate plus OAS", "新兴市场公司债 OAS", "credit", "percent", "bp", 100.0, DAILY, 5, "2023-01-01"),
    _s("NFCI", "Chicago Fed National Financial Conditions Index", "芝加哥联储金融条件指数 NFCI", "credit", "index", "index", 1.0, WEEKLY_FRI, 14, "2010-01-01"),
    _s("ANFCI", "Adjusted NFCI", "调整后 NFCI", "credit", "index", "index", 1.0, WEEKLY_FRI, 14, "2010-01-01"),
    _s("STLFSI4", "St. Louis Fed Financial Stress Index", "圣路易斯联储金融压力指数", "credit", "index", "index", 1.0, WEEKLY_FRI, 14, "2010-01-01"),
    _s("DCPF3M", "3-month AA financial commercial paper rate", "3个月金融 CP 利率", "credit", "percent", "pct", 1.0, DAILY, 7, "2023-01-01"),
    _s("DTB3", "3-month Treasury bill secondary market rate", "3个月 T-bill 利率", "credit", "percent", "pct", 1.0, DAILY, 7, "2023-01-01"),
    # ---- Rates and term premium (4d) ---------------------------------------------------
    _s("DGS2", "2-year Treasury yield", "2年期国债收益率", "rates", "percent", "pct", 1.0, DAILY, 5, "2010-01-01"),
    _s("DGS5", "5-year Treasury yield", "5年期国债收益率", "rates", "percent", "pct", 1.0, DAILY, 5, "2010-01-01"),
    _s("DGS10", "10-year Treasury yield", "10年期国债收益率", "rates", "percent", "pct", 1.0, DAILY, 5, "2010-01-01"),
    _s("DGS30", "30-year Treasury yield", "30年期国债收益率", "rates", "percent", "pct", 1.0, DAILY, 5, "2010-01-01", "state"),
    _s("T10Y2Y", "10-year minus 2-year Treasury spread", "2s10s 利差", "rates", "percent", "bp", 100.0, DAILY, 5, "2010-01-01"),
    _s("T10Y3M", "10-year minus 3-month Treasury spread", "3m10y 利差", "rates", "percent", "bp", 100.0, DAILY, 5, "2010-01-01"),
    _s("DFII10", "10-year TIPS real yield", "10年期实际利率", "rates", "percent", "pct", 1.0, DAILY, 5, "2010-01-01", "state"),
    _s("T10YIE", "10-year breakeven inflation", "10年期盈亏平衡通胀", "rates", "percent", "pct", 1.0, DAILY, 5, "2010-01-01"),
    _s("THREEFYTP10", "Kim-Wright 10-year term premium (model estimate)", "Kim-Wright 10年期期限溢价(模型估计)", "rates", "percent", "pct", 1.0, DAILY, 7, "2010-01-01", "state"),
    _s("TASACBW027SBOG", "Commercial banks: Treasury and agency securities", "商业银行持有国债和机构债", "rates", "billions", "$B", 1.0, WEEKLY_H8, 14, "2018-01-01"),
    _s("DTWEXBGS", "Nominal broad US dollar index", "广义美元指数", "rates", "index", "index", 1.0, DAILY, 8, "2018-01-01"),
    # ---- Volatility fallback ---------------------------------------------------------
    _s("VIXCLS", "CBOE Volatility Index close", "VIX 收盘", "vol", "index", "index", 1.0, DAILY, 5, "2025-01-01"),
    _s("VXVCLS", "CBOE 3-month Volatility Index close", "VIX3M 收盘", "vol", "index", "index", 1.0, DAILY, 5, "2025-01-01"),
)

BY_ID: dict[str, FredSpec] = {s.id: s for s in CATALOG}


def specs_for(*sections: str) -> list[FredSpec]:
    return [s for s in CATALOG if s.section in sections]
