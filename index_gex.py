"""Homebrew SPY/QQQ dealer gamma: pure functions (no network).

SqueezeMetrics naive convention: dealers long calls (+) and short puts (-), open-interest weighted
Black-Scholes gamma expressed in $bn per 1% underlying move. The network layer (Yahoo option
chains) stays in generate_dashboard.py and passes plain contract tuples in here.
"""
from __future__ import annotations

import json
import re
from math import exp, log, pi, sqrt
from typing import Any, Iterable

LOOKAHEAD_DAYS = 45
MAX_EXPIRIES = 10
SNAP_MAX = 400          # rolling daily-snapshot cap per symbol
PCTILE_MIN_DAYS = 60    # suppress percentile until this much history
MIN_CONTRACTS = 200     # fewer usable contracts than this is treated as an empty chain
MIN_EXPIRIES = 3
STATE_RE = re.compile(r'<script id="hgex-state" type="application/json">(.*?)</script>', re.DOTALL)


def load_state(prev_html: str) -> dict[str, dict[str, dict[str, Any]]]:
    """Extract {symbol: {date: snapshot}} from a prior index.html, dropping thin snapshots."""
    if not prev_html:
        return {}
    m = STATE_RE.search(prev_html)
    if not m:
        return {}
    try:
        raw = json.loads(m.group(1))
    except (ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for sym, snaps in raw.items():
        if isinstance(snaps, dict):
            out[sym] = {d: v for d, v in snaps.items() if isinstance(v, dict) and (v.get("n_contracts") or 0) >= MIN_CONTRACTS}
    return out


def state_block(state: dict) -> str:
    payload = json.dumps(state, separators=(",", ":")).replace("</", "<\\/")
    return '<script id="hgex-state" type="application/json">' + payload + "</script>"


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def bs_gamma(S: float, K: float, T: float, sigma: float, r: float) -> float:
    """Black-Scholes gamma = phi(d1) / (S * sigma * sqrt(T)); zero for invalid inputs."""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1 = (log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    return _norm_pdf(d1) / (S * sigma * sqrt(T))


def clean_contract(K: Any, oi: Any, iv: Any) -> tuple[float, float, float] | None:
    """Return floats when the contract is usable, else None (NaN, no OI, absurd IV)."""
    try:
        K, oi, iv = float(K), float(oi), float(iv)
    except (TypeError, ValueError):
        return None
    if not (K == K and oi == oi and iv == iv):
        return None
    if oi <= 0 or iv <= 0.001 or iv > 5.0:
        return None
    return K, oi, iv


def build_reading(symbol: str, spot: float, contracts: Iterable[tuple[float, bool, Any, Any, Any]], n_ok_exp: int, r: float) -> dict[str, Any] | None:
    """contracts: (T_years, is_call, strike, open_interest, implied_vol). None when the chain is too thin."""
    by_strike: dict[float, float] = {}
    call_by: dict[float, float] = {}
    put_by: dict[float, float] = {}
    n_contracts = 0
    for T, is_call, K, oi, iv in contracts:
        c = clean_contract(K, oi, iv)
        if c is None:
            continue
        K, oi, iv = c
        g = bs_gamma(spot, K, T, iv, r)
        dollar = g * oi * 100.0 * spot * spot * 0.01        # $ per 1% move
        signed = dollar if is_call else -dollar
        by_strike[K] = by_strike.get(K, 0.0) + signed
        side = call_by if is_call else put_by
        side[K] = side.get(K, 0.0) + dollar
        n_contracts += 1
    if n_ok_exp < MIN_EXPIRIES or n_contracts < MIN_CONTRACTS:
        return None

    net_gex = sum(by_strike.values()) / 1e9
    strikes = sorted(by_strike)
    flip, cum, prev_s, prev_c, crossings = None, 0.0, None, None, []
    for K in strikes:
        cum += by_strike[K]
        if prev_c is not None and prev_c != 0 and (prev_c < 0) != (cum < 0):
            x = prev_s + (K - prev_s) * (0.0 - prev_c) / (cum - prev_c) if cum != prev_c else K
            crossings.append(x)
        prev_s, prev_c = K, cum
    if crossings:
        flip = min(crossings, key=lambda x: abs(x - spot))
    walls = [(round(k, 2), v / 1e9) for k, v in sorted(by_strike.items(), key=lambda kv: -abs(kv[1]))[:3]]
    call_wall = max(call_by.items(), key=lambda kv: kv[1])[0] if call_by else None
    put_wall = max(put_by.items(), key=lambda kv: kv[1])[0] if put_by else None
    lo, hi = spot * 0.9, spot * 1.1
    profile = [(round(k, 2), round(by_strike[k] / 1e9, 4)) for k in strikes if lo <= k <= hi]
    return {"symbol": symbol, "spot": spot, "net_gex": net_gex, "flip": flip, "call_wall": call_wall,
            "put_wall": put_wall, "walls": walls, "n_expiries": n_ok_exp, "n_contracts": n_contracts, "profile": profile}


def add_snapshot(snaps: dict[str, dict[str, Any]], day: str, reading: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snaps[day] = {"net_gex": reading["net_gex"], "flip": reading["flip"], "spot": reading["spot"],
                  "n_expiries": reading["n_expiries"], "n_contracts": reading["n_contracts"]}
    if len(snaps) > SNAP_MAX:
        for d in sorted(snaps)[:-SNAP_MAX]:
            del snaps[d]
    return snaps


def cached_reading(symbol: str, snaps: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Last stored snapshot as a reading, flagged with its date. Never invents data."""
    if not snaps:
        return None
    last = sorted(snaps)[-1]
    s = snaps[last]
    return {"symbol": symbol, "spot": s.get("spot"), "net_gex": s.get("net_gex"), "flip": s.get("flip"),
            "call_wall": None, "put_wall": None, "walls": [], "n_expiries": s.get("n_expiries", 0),
            "n_contracts": s.get("n_contracts", 0), "profile": [], "cached_date": last}
