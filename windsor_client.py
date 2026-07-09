"""Data-access layer.

One function per connector, each returning a normalised pandas DataFrame so the
presentation layer never sees a raw connector field name. Live data comes from
the Windsor.ai connector API (the deployable equivalent of the Windsor.ai MCP's
get_data / get_fields — same connector slugs, same field IDs); when no API key is
configured the layer falls back to a bundled real-data snapshot so the app runs
out of the box. Swapping the source (live <-> snapshot <-> a warehouse) touches
only this file.

Field IDs are taken from config.FIELD_MAP, which was resolved via Windsor
`get_fields` and cached — field names are never guessed at call time.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import requests
import streamlit as st

import config

WINDSOR_BASE = "https://connectors.windsor.ai"
SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "sample_data", "snapshot.json")


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def brand_of(account: str) -> str:
    return "wowtamins" if "wowtamins" in str(account).lower() else "Vegavero"


def is_influencer_campaign(name: str) -> bool:
    """Boosted organic/creator posts are the closest influencer/creative signal
    on this account (no GRIN/Awin/affiliate connector). Flagged as a proxy."""
    return str(name).strip().lower().startswith("instagram post")


def get_api_key() -> Optional[str]:
    """WINDSOR_API_KEY from st.secrets or env. Never hard-coded."""
    try:
        if "WINDSOR_API_KEY" in st.secrets:
            return st.secrets["WINDSOR_API_KEY"]
    except Exception:
        pass
    return os.environ.get("WINDSOR_API_KEY")


@dataclass
class DataBundle:
    """Everything the UI needs, plus provenance so 'what's missing' is explicit."""
    ads_daily: pd.DataFrame
    ads_campaigns: pd.DataFrame
    ga4_daily: pd.DataFrame
    ga4_channel: pd.DataFrame
    ga4_new_returning: pd.DataFrame
    shopify_daily: pd.DataFrame
    shopify_products: pd.DataFrame
    instagram_accounts: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    mode: str = "demo"
    currency: str = config.DEFAULT_CURRENCY
    timezone: str = config.DEFAULT_TIMEZONE
    notes: list = field(default_factory=list)
    connector_status: dict = field(default_factory=dict)

    def note(self, msg: str) -> None:
        self.notes.append(msg)


# --------------------------------------------------------------------------- #
#  Live Windsor.ai connector API
# --------------------------------------------------------------------------- #
def windsor_get(connector: str, fields: list[str], date_from: str, date_to: str,
                api_key: str, extra: Optional[dict] = None) -> pd.DataFrame:
    """Thin wrapper over the Windsor connector data endpoint.

    Mirrors the MCP get_data contract: (connector, fields, date_from, date_to).
    Returns a DataFrame of raw connector columns (empty if the account has no
    rows in range). Raises requests.HTTPError on transport failure so callers
    can degrade gracefully.
    """
    params = {
        "api_key": api_key,
        "fields": ",".join(fields),
        "date_from": date_from,
        "date_to": date_to,
        "_renderer": "json",
    }
    if extra:
        params.update(extra)
    resp = requests.get(f"{WINDSOR_BASE}/{connector}", params=params, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    return pd.DataFrame(rows)


# ---- one function per connector (raw -> normalised) ------------------------ #
def _normalise_ads(df: pd.DataFrame, platform: str, cfg: dict, by: str) -> pd.DataFrame:
    """Normalise a raw ads frame to the common ads schema.

    `by` is 'date' (time series) or 'campaign' (breakdown). Missing metric
    columns (e.g. TikTok has no revenue field) are filled with 0 so downstream
    math never KeyErrors on partial field coverage.
    """
    if df.empty:
        cols = (["date"] if by == "date" else ["campaign"]) + \
            ["platform", "account", "brand", "spend", "impressions", "clicks",
             "purchases", "revenue"]
        if by == "campaign":
            cols.append("is_influencer")
        return pd.DataFrame(columns=cols)

    out = pd.DataFrame()
    if by == "date":
        out["date"] = pd.to_datetime(df["date"])
    else:
        out["campaign"] = df["campaign"].astype(str)
        out["is_influencer"] = out["campaign"].map(is_influencer_campaign)
    out["platform"] = platform
    out["account"] = df.get("account_name", "")
    out["brand"] = out["account"].map(brand_of)
    for c in ("spend", "impressions", "clicks"):
        out[c] = pd.to_numeric(df.get(c, 0), errors="coerce").fillna(0)
    pf, rf = cfg.get("purchases_field"), cfg.get("revenue_field")
    out["purchases"] = pd.to_numeric(df.get(pf, 0), errors="coerce").fillna(0) if pf else 0
    out["revenue"] = pd.to_numeric(df.get(rf, 0), errors="coerce").fillna(0) if rf else 0.0
    return out


def fetch_meta_ads(date_from, date_to, api_key, by="date"):
    cfg = config.FIELD_MAP["facebook"]
    dims = ["date"] if by == "date" else ["campaign"]
    fields = ["account_name"] + dims + cfg["metrics"]
    raw = windsor_get("facebook", fields, date_from, date_to, api_key)
    return _normalise_ads(raw, "Meta", cfg, by)


def fetch_google_ads(date_from, date_to, api_key, by="date"):
    cfg = config.FIELD_MAP["google_ads"]
    dims = ["date"] if by == "date" else ["campaign"]
    fields = ["account_name"] + dims + cfg["metrics"]
    raw = windsor_get("google_ads", fields, date_from, date_to, api_key)
    return _normalise_ads(raw, "Google", cfg, by)


def fetch_tiktok_ads(date_from, date_to, api_key, by="date"):
    cfg = config.FIELD_MAP["tiktok"]
    dims = ["date"] if by == "date" else ["campaign"]
    fields = ["account_name"] + dims + cfg["metrics"]
    try:
        raw = windsor_get("tiktok", fields, date_from, date_to, api_key)
    except requests.HTTPError:
        raw = pd.DataFrame()
    return _normalise_ads(raw, "TikTok", cfg, by)


def fetch_ga4(date_from, date_to, api_key, dim="date"):
    """dim in {'date','default_channel_group','new_vs_returning'}."""
    cfg = config.FIELD_MAP["googleanalytics4"]
    fields = [dim] + cfg["metrics"]
    raw = windsor_get("googleanalytics4", fields, date_from, date_to, api_key)
    if raw.empty:
        return raw
    # Multiple properties may return the same key; aggregate.
    metrics = [m for m in cfg["metrics"] if m in raw.columns]
    for m in metrics:
        raw[m] = pd.to_numeric(raw[m], errors="coerce").fillna(0)
    agg = raw.groupby(dim, as_index=False)[metrics].sum()
    rename = {"totalrevenue": "revenue"}
    agg = agg.rename(columns=rename)
    if dim == "date":
        agg["date"] = pd.to_datetime(agg["date"])
    return agg


def fetch_instagram(date_from, date_to, api_key):
    """Instagram organic per-account insights. Engagement metrics and reach live
    in different Windsor tables (and `follower_count` is limited to ~30 days), so
    we pull them separately and merge on account. Returns empty on any failure."""
    def brand(acc):
        return "wowtamins" if "wowtamins" in str(acc).lower() else "Vegavero"
    try:
        eng = windsor_get("instagram",
                          ["account_name", "likes", "comments", "shares", "total_interactions"],
                          date_from, date_to, api_key)
        rch = windsor_get("instagram", ["account_name", "reach"], date_from, date_to, api_key)
    except requests.HTTPError:
        return pd.DataFrame()
    if eng.empty:
        return pd.DataFrame()
    for c in ("likes", "comments", "shares", "total_interactions"):
        eng[c] = pd.to_numeric(eng.get(c, 0), errors="coerce").fillna(0)
    eng = eng.groupby("account_name", as_index=False).sum(numeric_only=True)
    if not rch.empty:
        rch["reach"] = pd.to_numeric(rch["reach"], errors="coerce").fillna(0)
        rch = rch.groupby("account_name", as_index=False)["reach"].sum()
        eng = eng.merge(rch, on="account_name", how="left")
    else:
        eng["reach"] = float("nan")
    # new followers (best-effort; field caps at ~30 days)
    try:
        fol = windsor_get("instagram", ["account_name", "follower_count"],
                          _clamp_30d(date_from, date_to), date_to, api_key)
        if not fol.empty:
            fol = fol.groupby("account_name", as_index=False)["follower_count"].sum()
            eng = eng.merge(fol, on="account_name", how="left")
    except requests.HTTPError:
        pass
    eng = eng.rename(columns={"account_name": "account", "follower_count": "new_followers"})
    eng["brand"] = eng["account"].map(brand)
    return eng


def _clamp_30d(date_from, date_to):
    """follower_count only supports ~30 days; clamp the from-date accordingly."""
    try:
        d_from, d_to = pd.to_datetime(date_from), pd.to_datetime(date_to)
        floor = d_to - pd.Timedelta(days=29)
        return max(d_from, floor).date().isoformat()
    except Exception:
        return date_from


def fetch_shopify(date_from, date_to, api_key):
    """Shopify sales. Windsor supports a `shopify` connector, but it is not
    connected on this account, so live pulls return empty and the caller falls
    back / surfaces the gap. When connected, wire the ShopifyQL-equivalent fields
    here (total_sales, net_sales, orders)."""
    try:
        raw = windsor_get("shopify", ["date", "total_sales", "net_sales", "orders"],
                          date_from, date_to, api_key)
    except requests.HTTPError:
        raw = pd.DataFrame()
    return raw


# --------------------------------------------------------------------------- #
#  Snapshot (demo / offline fallback) -- real pull, 2026-04-10 .. 2026-07-09
# --------------------------------------------------------------------------- #
def _load_snapshot() -> dict:
    with open(SNAPSHOT_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _bundle_from_snapshot(date_from: str, date_to: str) -> DataBundle:
    snap = _load_snapshot()
    df_from, df_to = pd.to_datetime(date_from), pd.to_datetime(date_to)

    ads = pd.DataFrame(snap["ads_daily"])
    ads["date"] = pd.to_datetime(ads["date"])
    ads = ads[(ads["date"] >= df_from) & (ads["date"] <= df_to)]

    camp = pd.DataFrame(snap["ads_campaigns"])

    g_daily = pd.DataFrame(snap["ga4_daily"])
    g_daily["date"] = pd.to_datetime(g_daily["date"])
    g_daily = g_daily[(g_daily["date"] >= df_from) & (g_daily["date"] <= df_to)]

    g_channel = pd.DataFrame(snap["ga4_channel"])
    g_nr = pd.DataFrame(snap["ga4_new_returning"])

    sh_daily = pd.DataFrame(snap["shopify_daily"])
    sh_daily["date"] = pd.to_datetime(sh_daily["date"])
    sh_daily = sh_daily[(sh_daily["date"] >= df_from) & (sh_daily["date"] <= df_to)]

    sh_prod = pd.DataFrame(snap["shopify_products"])
    ig = pd.DataFrame(snap.get("instagram_accounts", []))

    b = DataBundle(
        ads_daily=ads, ads_campaigns=camp, ga4_daily=g_daily, ga4_channel=g_channel,
        ga4_new_returning=g_nr, shopify_daily=sh_daily, shopify_products=sh_prod,
        instagram_accounts=ig,
        mode="demo", currency=snap["meta"]["currency"], timezone=snap["meta"]["timezone"],
        connector_status=snap["meta"]["connectors_status"],
    )
    b.note(f"Demo mode — bundled real snapshot from {snap['meta']['source']}. "
           "Set WINDSOR_API_KEY in secrets and enable live mode for fresh data.")
    b.note("Campaign / channel / new-vs-returning breakdowns reflect the pull's "
           "~30-day window, not the selected sub-range.")
    return b


# --------------------------------------------------------------------------- #
#  Orchestrator (cached)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=config.DEFAULT_CACHE_TTL_SECONDS, show_spinner="Loading data…")
def load_data(date_from: str, date_to: str, live: bool) -> DataBundle:
    """Return a DataBundle for the range. Cached with TTL; the sidebar refresh
    button clears the cache. `live=False` or a missing key -> demo snapshot."""
    api_key = get_api_key()
    if not live or not api_key:
        b = _bundle_from_snapshot(date_from, date_to)
        if live and not api_key:
            b.note("Live mode requested but no WINDSOR_API_KEY found — showing demo data.")
        return b

    notes, status = [], {}
    try:
        meta = pd.concat([fetch_meta_ads(date_from, date_to, api_key, "date"),
                          fetch_google_ads(date_from, date_to, api_key, "date"),
                          fetch_tiktok_ads(date_from, date_to, api_key, "date")],
                         ignore_index=True)
        camp = pd.concat([fetch_meta_ads(date_from, date_to, api_key, "campaign"),
                          fetch_google_ads(date_from, date_to, api_key, "campaign")],
                         ignore_index=True)
        g_daily = fetch_ga4(date_from, date_to, api_key, "date")
        g_channel = fetch_ga4(date_from, date_to, api_key, "default_channel_group")
        g_nr = fetch_ga4(date_from, date_to, api_key, "new_vs_returning")
        shop = fetch_shopify(date_from, date_to, api_key)
        ig = fetch_instagram(date_from, date_to, api_key)
    except requests.RequestException as exc:
        b = _bundle_from_snapshot(date_from, date_to)
        b.note(f"Live Windsor request failed ({exc}); fell back to demo snapshot.")
        return b

    # channel/new_returning column tidy-up to the UI schema
    if not g_channel.empty:
        g_channel = g_channel.rename(columns={"default_channel_group": "channel"})
    if not g_nr.empty:
        g_nr = g_nr.rename(columns={"new_vs_returning": "segment"})
        g_nr = g_nr[g_nr["segment"].isin(["new", "returning"])]

    # Shopify not on Windsor here -> surface the gap rather than fail
    if shop.empty:
        notes.append("Shopify is not connected to Windsor on this account; MER, CAC "
                     "and margin fall back to platform-reported revenue where store "
                     "revenue is unavailable. Connect Shopify in Windsor for true MER.")
        shop_daily = pd.DataFrame(columns=["date", "total_sales", "net_sales", "orders", "aov"])
    else:
        shop_daily = shop.rename(columns={})
        shop_daily["date"] = pd.to_datetime(shop_daily["date"])

    status = {
        "Meta Ads": f"{(meta['platform']=='Meta').sum()} daily rows",
        "Google Ads": f"{(meta['platform']=='Google').sum()} daily rows",
        "TikTok Ads": "no rows in range" if (meta["platform"] == "TikTok").sum() == 0
                       else f"{(meta['platform']=='TikTok').sum()} rows",
        "GA4": f"{len(g_daily)} daily rows",
        "Shopify": "connected" if not shop.empty else "not connected (Windsor)",
    }
    b = DataBundle(
        ads_daily=meta, ads_campaigns=camp, ga4_daily=g_daily, ga4_channel=g_channel,
        ga4_new_returning=g_nr, shopify_daily=shop_daily,
        shopify_products=pd.DataFrame(columns=["product", "total_sales", "items", "orders"]),
        instagram_accounts=ig,
        mode="live", currency=config.DEFAULT_CURRENCY, timezone=config.DEFAULT_TIMEZONE,
        connector_status=status,
    )
    for n in notes:
        b.note(n)
    return b
