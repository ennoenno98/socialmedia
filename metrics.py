"""KPI computations.

Pure functions over a DataBundle + an assumptions dict. No Streamlit here, so the
math is unit-testable and the presentation layer stays thin. Every metric that
leans on an assumption or a proxy is flagged so the UI can surface the caveat.
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd

NA = float("nan")


def _safe_div(a, b):
    try:
        return a / b if b else NA
    except ZeroDivisionError:
        return NA


# --------------------------------------------------------------------------- #
#  Unit-economics helpers (all driven by sidebar assumptions)
# --------------------------------------------------------------------------- #
def margin_pct(a: dict) -> float:
    """Variable contribution margin as a fraction of revenue."""
    if a.get("avg_order_margin_pct"):
        return a["avg_order_margin_pct"] / 100.0
    m = 1.0 - a["cogs_pct"] / 100.0 - a["payment_fee_pct"] / 100.0
    return max(0.0, m)


def monthly_cm_per_customer(a: dict) -> float:
    """Assumption-derived monthly gross profit per acquired customer, used for
    CAC-payback. = LTV * margin% / LTV window (months)."""
    return _safe_div(a["avg_ltv"] * margin_pct(a), a["ltv_window_months"])


def payback_months(cac: float, a: dict) -> float:
    mcm = monthly_cm_per_customer(a)
    return _safe_div(cac, mcm)


# --------------------------------------------------------------------------- #
#  Aggregates
# --------------------------------------------------------------------------- #
def ads_totals(ads: pd.DataFrame) -> dict:
    if ads.empty:
        return dict(spend=0.0, impressions=0.0, clicks=0.0, purchases=0.0, revenue=0.0)
    return dict(
        spend=float(ads["spend"].sum()),
        impressions=float(ads["impressions"].sum()),
        clicks=float(ads["clicks"].sum()),
        purchases=float(ads["purchases"].sum()),
        revenue=float(ads["revenue"].sum()),
    )


def shopify_totals(shop: pd.DataFrame) -> dict:
    if shop.empty:
        return dict(total_sales=NA, net_sales=NA, orders=NA)
    return dict(
        total_sales=float(shop["total_sales"].sum()),
        net_sales=float(shop["net_sales"].sum()),
        orders=float(shop["orders"].sum()),
    )


def new_returning_shares(nr: pd.DataFrame) -> dict:
    """New / returning transaction shares from GA4 (the new-customer proxy)."""
    if nr.empty or "transactions" not in nr:
        return dict(new_share=NA, returning_share=NA, new_txn=NA, returning_txn=NA)
    m = nr.set_index("segment")["transactions"].to_dict()
    new_t = float(m.get("new", 0))
    ret_t = float(m.get("returning", 0))
    tot = new_t + ret_t
    return dict(new_share=_safe_div(new_t, tot), returning_share=_safe_div(ret_t, tot),
                new_txn=new_t, returning_txn=ret_t)


# --------------------------------------------------------------------------- #
#  Section 1 — Efficiency / Spend
# --------------------------------------------------------------------------- #
def efficiency(bundle, a: dict) -> dict:
    ads = ads_totals(bundle.ads_daily)
    shop = shopify_totals(bundle.shopify_daily)
    nr = new_returning_shares(bundle.ga4_new_returning)

    store_rev = shop["total_sales"]
    if math.isnan(store_rev):  # Shopify not connected -> fall back, flagged
        store_rev = ads["revenue"]

    orders = shop["orders"]
    est_new = orders * nr["new_share"] if not math.isnan(orders) and not math.isnan(nr["new_share"]) else NA

    platform_roas = _safe_div(ads["revenue"], ads["spend"])
    mer = _safe_div(store_rev, ads["spend"])
    cac_blended = _safe_div(ads["spend"], orders)
    ncac = _safe_div(ads["spend"], est_new)

    return dict(
        spend=ads["spend"],
        impressions=ads["impressions"],
        clicks=ads["clicks"],
        cpm=_safe_div(ads["spend"], ads["impressions"]) * 1000,
        cpc=_safe_div(ads["spend"], ads["clicks"]),
        ctr=_safe_div(ads["clicks"], ads["impressions"]),
        platform_revenue=ads["revenue"],
        store_revenue=store_rev,
        store_revenue_is_fallback=math.isnan(shop["total_sales"]),
        platform_roas=platform_roas,
        mer=mer,
        # attribution reality-check: how much MER exceeds platform-claimed ROAS
        attribution_gap_abs=(mer - platform_roas) if not (math.isnan(mer) or math.isnan(platform_roas)) else NA,
        attribution_gap_pct=_safe_div(mer - platform_roas, platform_roas),
        orders=orders,
        est_new_customers=est_new,
        new_share=nr["new_share"],
        cac=cac_blended,
        ncac=ncac,
        payback_months=payback_months(ncac, a),
    )


# --------------------------------------------------------------------------- #
#  Section 2 — Funnel / Conversion
# --------------------------------------------------------------------------- #
def funnel(bundle, a: dict) -> dict:
    g = bundle.ga4_daily
    nr = new_returning_shares(bundle.ga4_new_returning)
    if g.empty:
        return dict(available=False)
    s = float(g["sessions"].sum())
    atc = float(g["add_to_carts"].sum())
    cko = float(g["checkouts"].sum())
    txn = float(g["transactions"].sum())
    return dict(
        available=True,
        sessions=s, add_to_carts=atc, checkouts=cko, transactions=txn,
        atc_rate=_safe_div(atc, s),
        checkout_rate=_safe_div(cko, s),
        conversion_rate=_safe_div(txn, s),
        cart_to_checkout=_safe_div(cko, atc),
        checkout_to_purchase=_safe_div(txn, cko),
        new_share=nr["new_share"],
        returning_share=nr["returning_share"],
        new_txn=nr["new_txn"],
        returning_txn=nr["returning_txn"],
    )


def creative_cvr(bundle) -> pd.DataFrame:
    """Click->purchase CVR by campaign/creative (proxy for landing-page CVR;
    isolates creative from targeting only to the extent clicks are comparable)."""
    c = bundle.ads_campaigns
    if c.empty:
        return pd.DataFrame()
    df = c.copy()
    df["click_cvr"] = df.apply(lambda r: _safe_div(r["purchases"], r["clicks"]), axis=1)
    df["roas"] = df.apply(lambda r: _safe_div(r["revenue"], r["spend"]), axis=1)
    return df.sort_values("spend", ascending=False)


# --------------------------------------------------------------------------- #
#  Section 3 — Retention / Quality
# --------------------------------------------------------------------------- #
def retention(bundle, a: dict) -> dict:
    """Repeat/LTV/margin. True cohort repeat-by-source needs Shopify order-level
    customer data (order_date + customer_id), which is not in the connected
    sources; those cells are marked unavailable and a GA4 returning-order share
    is offered as a blended proxy."""
    nr = new_returning_shares(bundle.ga4_new_returning)
    eff = efficiency(bundle, a)
    shop = shopify_totals(bundle.shopify_daily)
    ads = ads_totals(bundle.ads_daily)

    # blended per-order economics
    orders = shop["orders"]
    gross_aov = _safe_div(shop["total_sales"], orders)
    net_aov = _safe_div(shop["net_sales"], orders)
    if math.isnan(gross_aov):  # no Shopify -> proxy AOV from attributed revenue
        gross_aov = net_aov = _safe_div(ads["revenue"], ads["purchases"])

    cogs = net_aov * a["cogs_pct"] / 100.0 if not math.isnan(net_aov) else NA
    pay_fee = gross_aov * a["payment_fee_pct"] / 100.0 if not math.isnan(gross_aov) else NA
    cm2 = (net_aov - cogs - pay_fee) if not any(math.isnan(x) for x in (net_aov, cogs, pay_fee)) else NA
    cm3 = (cm2 - a["shipping_per_order"] - eff["ncac"]) if not (math.isnan(cm2) or math.isnan(eff["ncac"])) else NA

    ltv = a["avg_ltv"]
    ltv_cac = _safe_div(ltv, eff["ncac"])
    gm_ltv_cac = _safe_div(ltv * margin_pct(a), eff["ncac"])

    return dict(
        returning_order_share_proxy=nr["returning_share"],
        repeat_by_source_available=False,   # requires order-level Shopify data
        subscription_take_rate=a["subscription_take_rate"] / 100.0,  # assumption
        gross_aov=gross_aov, net_aov=net_aov,
        cm2_per_customer=cm2, cm3_per_customer=cm3,
        cm_margin_pct=margin_pct(a),
        ltv=ltv, ltv_cac=ltv_cac, gm_ltv_cac=gm_ltv_cac,
        payback_months=eff["payback_months"],
        payback_red=(not math.isnan(eff["payback_months"]) and eff["payback_months"] > a["payback_red_months"]),
    )


# --------------------------------------------------------------------------- #
#  Section 4 — Influencer-specific
# --------------------------------------------------------------------------- #
def influencer(bundle, a: dict) -> dict:
    c = bundle.ads_campaigns
    inf = c[c["is_influencer"]] if not c.empty else c
    n_deliverables = int(len(inf))
    spend = float(inf["spend"].sum()) if n_deliverables else 0.0
    impr = float(inf["impressions"].sum()) if n_deliverables else 0.0
    attr_orders = float(inf["purchases"].sum()) if n_deliverables else 0.0
    attr_rev = float(inf["revenue"].sum()) if n_deliverables else 0.0
    return dict(
        n_deliverables=n_deliverables,
        spend=spend,
        cost_per_deliverable=_safe_div(spend, n_deliverables),
        effective_cpm=_safe_div(spend, impr) * 1000 if impr else NA,
        promo_attributed_orders=attr_orders,
        promo_attributed_revenue=attr_rev,
        promo_source_connected=False,  # no GRIN/Awin/promo-code connector
    )


def incrementality_proxy(bundle, a: dict) -> dict:
    """MER during the selected flight vs a baseline window. Estimate only."""
    ts = mer_timeseries(bundle)
    if ts.empty:
        return dict(available=False)
    b_from = a.get("mer_baseline_from")
    b_to = a.get("mer_baseline_to")
    if b_from and b_to:
        base = ts[(ts["date"] >= pd.to_datetime(b_from)) & (ts["date"] <= pd.to_datetime(b_to))]
        flight = ts[(ts["date"] > pd.to_datetime(b_to))]
        basis = f"baseline {b_from} → {b_to}"
    else:
        base = ts.head(14)  # first 14 days of range
        flight = ts.iloc[14:]
        basis = "baseline = first 14 days of range"
    base_mer = _safe_div(base["shopify_revenue"].sum(), base["spend"].sum())
    flight_mer = _safe_div(flight["shopify_revenue"].sum(), flight["spend"].sum())
    return dict(available=True, basis=basis, baseline_mer=base_mer,
                flight_mer=flight_mer,
                lift_pct=_safe_div(flight_mer - base_mer, base_mer))


# --------------------------------------------------------------------------- #
#  Time series & breakdown tables
# --------------------------------------------------------------------------- #
def mer_timeseries(bundle) -> pd.DataFrame:
    ads = bundle.ads_daily
    shop = bundle.shopify_daily
    if ads.empty:
        return pd.DataFrame()
    spend = ads.groupby("date", as_index=False)["spend"].sum()
    attr = ads.groupby("date", as_index=False)["revenue"].sum().rename(columns={"revenue": "platform_revenue"})
    df = spend.merge(attr, on="date", how="outer")
    if not shop.empty:
        df = df.merge(shop[["date", "total_sales"]].rename(columns={"total_sales": "shopify_revenue"}),
                      on="date", how="left")
    else:
        df["shopify_revenue"] = df["platform_revenue"]
    df = df.sort_values("date")
    df["mer"] = df.apply(lambda r: _safe_div(r["shopify_revenue"], r["spend"]), axis=1)
    return df


def source_breakdown(bundle, a: dict) -> pd.DataFrame:
    """The headline cut: per source/creative spend, ROAS, CAC, CAC payback, and
    a repeat-rate proxy. Sortable in the UI. Repeat-by-source is a GA4-derived
    proxy pending order-level Shopify data."""
    c = bundle.ads_campaigns
    if c.empty:
        return pd.DataFrame()
    rows = []
    ret_proxy = new_returning_shares(bundle.ga4_new_returning)["returning_share"]
    for _, r in c.iterrows():
        cac = _safe_div(r["spend"], r["purchases"])
        rows.append(dict(
            platform=r["platform"], brand=r["brand"], campaign=r["campaign"],
            type="Influencer/creative" if r["is_influencer"] else "Performance",
            spend=r["spend"], clicks=r["clicks"], orders=r["purchases"],
            revenue=r["revenue"],
            roas=_safe_div(r["revenue"], r["spend"]),
            click_cvr=_safe_div(r["purchases"], r["clicks"]),
            cac=cac,
            cac_payback_months=payback_months(cac, a),
            repeat_90d_proxy=ret_proxy,
        ))
    df = pd.DataFrame(rows).sort_values("spend", ascending=False)
    return df


def channel_breakdown(bundle) -> pd.DataFrame:
    """GA4 default-channel-grouping split: sessions, funnel rates, revenue and
    new-visitor share per channel. Reflects the GA4 pull window (~30 days)."""
    c = bundle.ga4_channel
    if c.empty:
        return pd.DataFrame()
    df = c.copy()
    for col in ("sessions", "add_to_carts", "checkouts", "transactions", "revenue",
                "newusers", "totalusers"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df = df[df["sessions"] > 0]
    df["atc_rate"] = df.apply(lambda r: _safe_div(r["add_to_carts"], r["sessions"]), axis=1)
    df["cvr"] = df.apply(lambda r: _safe_div(r["transactions"], r["sessions"]), axis=1)
    df["rev_per_session"] = df.apply(lambda r: _safe_div(r["revenue"], r["sessions"]), axis=1)
    df["new_share"] = df.apply(lambda r: _safe_div(r["newusers"], r["totalusers"]), axis=1)
    df["rev_share"] = df["revenue"] / df["revenue"].sum() if df["revenue"].sum() else NA
    return df.sort_values("revenue", ascending=False)


def instagram_organic(bundle) -> pd.DataFrame:
    """Instagram organic per-account insights with an engagement rate on reach."""
    ig = bundle.instagram_accounts
    if ig.empty:
        return pd.DataFrame()
    df = ig.copy()
    for col in ("reach", "new_followers", "likes", "comments", "shares",
                "total_interactions"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["engagement_rate"] = df.apply(
        lambda r: _safe_div(r.get("total_interactions"), r.get("reach")), axis=1)
    return df.sort_values("total_interactions", ascending=False)


def instagram_creatives(bundle) -> pd.DataFrame:
    """Paid Instagram/boosted-post creatives (the influencer/creative proxy) with
    delivery + efficiency + attributed outcome per post."""
    c = bundle.ads_campaigns
    if c.empty:
        return pd.DataFrame()
    inf = c[c["is_influencer"]].copy()
    if inf.empty:
        return inf
    inf["post"] = inf["campaign"].str.replace(r"^Instagram post:\s*", "", regex=True).str.strip()
    inf["ctr"] = inf.apply(lambda r: _safe_div(r["clicks"], r["impressions"]), axis=1)
    inf["cpc"] = inf.apply(lambda r: _safe_div(r["spend"], r["clicks"]), axis=1)
    inf["cpm"] = inf.apply(lambda r: _safe_div(r["spend"], r["impressions"]) * 1000, axis=1)
    inf["roas"] = inf.apply(lambda r: _safe_div(r["revenue"], r["spend"]), axis=1)
    return inf.sort_values("impressions", ascending=False)


def influencer_code_attribution(bundle, a: dict, fee_map: dict | None = None) -> pd.DataFrame:
    """Per-discount-code attribution. Real facts from Shopify: orders, revenue,
    discount cost, returning split. The creator cost is a FIXED FEE per creator
    (fee_map[code], else the default flat fee) — not a commission. CAC/ROAS are
    derived from discount + fixed fee."""
    df = bundle.influencer_codes
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    for c in ("orders", "gross_sales", "discount", "net_sales", "total_sales",
              "returning_customers"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    fee_map = fee_map or {}
    default_fee = float(a.get("default_creator_fee", 0.0))
    mp = margin_pct(a)

    df["new_customers"] = (df["orders"] - df["returning_customers"]).clip(lower=0)
    df["new_rate"] = df.apply(lambda r: _safe_div(r["new_customers"], r["orders"]), axis=1)
    df["aov"] = df.apply(lambda r: _safe_div(r["total_sales"], r["orders"]), axis=1)
    df["discount_pct"] = df.apply(lambda r: _safe_div(r["discount"], r["gross_sales"]), axis=1)
    # fixed fee per creator (only for influencer codes)
    df["creator_fee"] = df.apply(
        lambda r: float(fee_map.get(r["code"], default_fee)) if r["category"] == "Influencer" else 0.0,
        axis=1)
    df["total_cost"] = df["discount"] + df["creator_fee"]
    df["roas"] = df.apply(lambda r: _safe_div(r["total_sales"], r["total_cost"]), axis=1)
    df["cac_new"] = df.apply(lambda r: _safe_div(r["total_cost"], r["new_customers"]), axis=1)
    df["contribution"] = df["net_sales"] * mp - df["creator_fee"]
    return df.sort_values("total_sales", ascending=False)


def influencer_code_summary(df: pd.DataFrame) -> dict:
    """Blended totals across INFLUENCER codes only (for the scorecard row)."""
    if df.empty:
        return dict(available=False)
    inf = df[df["category"] == "Influencer"]
    if inf.empty:
        return dict(available=False)
    rev = float(inf["total_sales"].sum())
    orders = float(inf["orders"].sum())
    new = float(inf["new_customers"].sum())
    cost = float(inf["total_cost"].sum())
    return dict(
        available=True, creators=int(inf["influencer"].nunique()),
        orders=orders, revenue=rev, new_customers=new,
        discount=float(inf["discount"].sum()), creator_fee=float(inf["creator_fee"].sum()),
        cost=cost, roas=_safe_div(rev, cost), cac_new=_safe_div(cost, new),
        contribution=float(inf["contribution"].sum()),
    )


# --------------------------------------------------------------------------- #
#  Blended scorecard (scalars, for period-over-period deltas)
# --------------------------------------------------------------------------- #
def scorecard(bundle, a: dict) -> dict:
    eff = efficiency(bundle, a)
    ret = retention(bundle, a)
    return dict(
        spend=eff["spend"],
        mer=eff["mer"],
        cac=eff["cac"],
        ncac=eff["ncac"],
        payback_months=eff["payback_months"],
        repeat_90d=ret["returning_order_share_proxy"],
    )
