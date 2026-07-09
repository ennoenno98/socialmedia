"""Influencer & Paid-Social Performance Dashboard — D2C supplements (Shopify).

Presentation layer only. Data access lives in windsor_client.py, KPI math in
metrics.py, assumptions/defaults in config.py. Audience is finance-fluent, so the
UI states numbers without metric hand-holding — but every proxy or assumption is
flagged inline.

Run:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import math

import altair as alt
import pandas as pd
import streamlit as st

import config
import metrics
from windsor_client import load_data

# --------------------------------------------------------------------------- #
#  Page + light theming
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="Paid-Social & Influencer Performance",
                   page_icon="📈", layout="wide")

# dataviz palette (blue / aqua categorical, validated defaults)
C_BLUE, C_AQUA, C_YELLOW, C_RED = "#2a78d6", "#1baf7a", "#eda100", "#e34948"
NA = float("nan")


# --------------------------------------------------------------------------- #
#  Formatting helpers
# --------------------------------------------------------------------------- #
def _cur(currency):
    return config.CURRENCY_SYMBOLS.get(currency, currency + " ")


def money(x, currency, decimals=0):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{_cur(currency)}{x:,.{decimals}f}"


def compact_money(x, currency):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = _cur(currency)
    ax = abs(x)
    if ax >= 1e6:
        return f"{s}{x/1e6:.2f}M"
    if ax >= 1e3:
        return f"{s}{x/1e3:.1f}K"
    return f"{s}{x:,.0f}"


def pct(x, decimals=1):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x*100:.{decimals}f}%"


def ratio(x, decimals=2):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x:.{decimals}f}×"


def num(x, decimals=0):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x:,.{decimals}f}"


def delta_str(cur, prev, kind):
    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in (cur, prev)):
        return None
    d = cur - prev
    if kind == "money":
        return f"{d:+,.0f}"
    if kind == "pct":
        return f"{d*100:+.1f} pp"
    if kind == "ratio":
        return f"{d:+.2f}×"
    if kind == "months":
        return f"{d:+.1f} mo"
    return f"{d:+,.1f}"


# --------------------------------------------------------------------------- #
#  Sidebar — assumptions (all find-and-replaceable placeholder defaults)
# --------------------------------------------------------------------------- #
def sidebar():
    st.sidebar.title("Controls")

    st.sidebar.subheader("Data source")
    live = st.sidebar.toggle("Live Windsor.ai data", value=False,
                             help="Off = bundled real snapshot. On = pull live via "
                                  "Windsor.ai connector API (needs WINDSOR_API_KEY in secrets).")
    if st.sidebar.button("↻ Refresh (clear cache)", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.subheader("Reporting basis")
    st.sidebar.caption("Asked, not assumed — set to match your books.")
    currency = st.sidebar.selectbox("Currency", list(config.CURRENCY_SYMBOLS),
                                    index=list(config.CURRENCY_SYMBOLS).index(config.DEFAULT_CURRENCY))
    timezone = st.sidebar.text_input("Reporting timezone", config.DEFAULT_TIMEZONE)

    st.sidebar.subheader("Date range")
    default_end = dt.date(2026, 7, 9)
    preset = st.sidebar.selectbox("Preset", list(config.DATE_PRESETS) + ["Custom"], index=2)
    if preset == "Custom":
        rng = st.sidebar.date_input("Custom range",
                                    (default_end - dt.timedelta(days=29), default_end))
        date_from, date_to = (rng if isinstance(rng, tuple) and len(rng) == 2
                              else (default_end - dt.timedelta(days=29), default_end))
    else:
        days = config.DATE_PRESETS[preset]
        date_to = default_end
        date_from = default_end - dt.timedelta(days=days - 1)

    st.sidebar.subheader("Attribution")
    cac_days = st.sidebar.number_input("CAC attribution window (days, click)",
                                       1, 90, config.DEFAULT_CAC_ATTRIBUTION_DAYS)

    st.sidebar.subheader("Unit economics")
    st.sidebar.caption("Placeholders — replace with finance's figures.")
    cogs = st.sidebar.number_input("Blended COGS (% of net revenue)", 0.0, 100.0,
                                   config.DEFAULT_COGS_PCT, 0.5)
    fee = st.sidebar.number_input("Payment processing (% of gross)", 0.0, 20.0,
                                  config.DEFAULT_PAYMENT_FEE_PCT, 0.1)
    shipping = st.sidebar.number_input("Shipping + fulfilment (per order)", 0.0, 100.0,
                                       config.DEFAULT_SHIPPING_PER_ORDER, 0.5)

    st.sidebar.subheader("LTV & retention")
    st.sidebar.caption("Placeholders.")
    ltv = st.sidebar.number_input("Avg customer LTV (gross)", 0.0, 10000.0,
                                  config.DEFAULT_AVG_CUSTOMER_LTV, 5.0)
    ltv_win = st.sidebar.number_input("LTV window (months)", 1, 60,
                                      config.DEFAULT_LTV_WINDOW_MONTHS)
    payback_red = st.sidebar.number_input("Flag CAC payback above (months)", 0.5, 24.0,
                                          config.DEFAULT_PAYBACK_RED_MONTHS, 0.5)
    repeat_win = st.sidebar.selectbox("Repeat-rate window (days)", [30, 60, 90],
                                      index=[30, 60, 90].index(config.DEFAULT_REPEAT_WINDOW_DAYS))
    sub_take = st.sidebar.number_input("Subscribe & Save take-rate (%)", 0.0, 100.0,
                                       config.DEFAULT_SUBSCRIPTION_TAKE_RATE, 0.5)

    st.sidebar.subheader("Influencer attribution")
    default_fee = st.sidebar.number_input("Fixed fee per creator (default, per period)",
                                          0.0, 100000.0, config.DEFAULT_CREATOR_FIXED_FEE, 25.0,
                                          help="Flat fee paid per creator for the selected "
                                               "period (creators are paid a fixed fee, not a "
                                               "commission). Override per creator in the "
                                               "Instagram tab.")

    st.sidebar.subheader("Incrementality")
    use_baseline = st.sidebar.checkbox("Set MER baseline window", value=False)
    b_from = b_to = None
    if use_baseline:
        br = st.sidebar.date_input("Baseline window",
                                   (date_from, date_from + dt.timedelta(days=13)))
        if isinstance(br, tuple) and len(br) == 2:
            b_from, b_to = br[0].isoformat(), br[1].isoformat()

    assumptions = dict(
        cac_attribution_days=cac_days, cogs_pct=cogs, payment_fee_pct=fee,
        shipping_per_order=shipping, avg_order_margin_pct=config.DEFAULT_AVG_ORDER_MARGIN_PCT,
        avg_ltv=ltv, ltv_window_months=ltv_win, payback_red_months=payback_red,
        repeat_window_days=repeat_win, subscription_take_rate=sub_take,
        default_creator_fee=default_fee,
        mer_baseline_from=b_from, mer_baseline_to=b_to,
    )
    return live, currency, timezone, date_from, date_to, assumptions


# --------------------------------------------------------------------------- #
#  Charts
# --------------------------------------------------------------------------- #
def chart_spend_vs_revenue(ts, currency):
    if ts.empty:
        return None
    d = ts.melt("date", ["spend", "shopify_revenue"], "Series", "value")
    d["Series"] = d["Series"].map({"spend": "Ad spend", "shopify_revenue": "Store revenue"})
    return (
        alt.Chart(d).mark_line(strokeWidth=2, point=False)
        .encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("value:Q", title=f"{currency}/day", axis=alt.Axis(format="~s")),
            color=alt.Color("Series:N", scale=alt.Scale(range=[C_BLUE, C_AQUA]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=[alt.Tooltip("date:T"), "Series:N",
                     alt.Tooltip("value:Q", format=",.0f")],
        ).properties(height=260)
    )


def chart_mer(ts):
    if ts.empty:
        return None
    return (
        alt.Chart(ts).mark_line(strokeWidth=2, color=C_BLUE)
        .encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("mer:Q", title="MER (revenue ÷ spend)"),
            tooltip=[alt.Tooltip("date:T"), alt.Tooltip("mer:Q", format=".2f")],
        ).properties(height=220)
    )


def chart_channel(cb, currency):
    if cb.empty:
        return None
    return (
        alt.Chart(cb).mark_bar(color=C_BLUE, cornerRadiusEnd=4, size=18)
        .encode(
            x=alt.X("revenue:Q", title=f"Revenue ({currency})", axis=alt.Axis(format="~s")),
            y=alt.Y("channel:N", sort="-x", title=None),
            tooltip=[alt.Tooltip("channel:N", title="Channel"),
                     alt.Tooltip("revenue:Q", format=",.0f"),
                     alt.Tooltip("sessions:Q", format=",.0f"),
                     alt.Tooltip("cvr:Q", format=".2%")],
        ).properties(height=360)
    )


def chart_funnel(f):
    steps = pd.DataFrame({
        "Step": ["Sessions", "Add to cart", "Checkout", "Purchase"],
        "Count": [f["sessions"], f["add_to_carts"], f["checkouts"], f["transactions"]],
    })
    steps["order"] = range(len(steps))
    return (
        alt.Chart(steps).mark_bar(color=C_BLUE, cornerRadiusEnd=4, size=26)
        .encode(
            x=alt.X("Count:Q", title=None, axis=alt.Axis(format="~s")),
            y=alt.Y("Step:N", sort=alt.EncodingSortField("order"), title=None),
            tooltip=[alt.Tooltip("Count:Q", format=",.0f")],
        ).properties(height=200)
    )


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    live, currency, timezone, date_from, date_to, a = sidebar()
    df_s, dt_s = date_from.isoformat(), date_to.isoformat()

    bundle = load_data(df_s, dt_s, live)
    currency = currency or bundle.currency

    # previous equal-length window for period-over-period deltas
    span = (date_to - date_from).days + 1
    prev_to = date_from - dt.timedelta(days=1)
    prev_from = prev_to - dt.timedelta(days=span - 1)
    prev_bundle = load_data(prev_from.isoformat(), prev_to.isoformat(), live)

    # -- header ---------------------------------------------------------------
    st.title("Influencer & Paid-Social Performance")
    st.caption(f"Vegavero — Shopify D2C supplements · {df_s} → {dt_s} · {currency} · {timezone}")

    mode_badge = "🟢 LIVE (Windsor.ai)" if bundle.mode == "live" else "🟡 DEMO (bundled snapshot)"
    st.markdown(f"**Data mode:** {mode_badge}")

    with st.expander("Data provenance, connector status & caveats", expanded=(bundle.mode == "demo")):
        cols = st.columns(2)
        with cols[0]:
            st.markdown("**Connector status**")
            for k, v in bundle.connector_status.items():
                st.markdown(f"- **{k}:** {v}")
        with cols[1]:
            st.markdown("**Notes**")
            for n in bundle.notes:
                st.markdown(f"- {n}")
        st.info(
            "**Read before acting:**  \n"
            "• **Subscription revenue** is recognised as *fulfilled, not booked upfront* — "
            "LTV:CAC below does **not** credit full LTV against first-order CAC; treat LTV:CAC "
            "as a gross-margin view.  \n"
            "• **Influencer attribution** is promo-code / link based and **under-credits true "
            "lift**; the incrementality figure is an *estimate*. Boosted organic posts are used "
            "as the influencer/creative proxy (no GRIN/Awin connector on this account).  \n"
            "• **Compliance:** health / structure-function claims in creative are a regulatory "
            "exposure — review creative metadata before scaling any winner.",
            icon="⚠️",
        )

    # -- blended scorecard ----------------------------------------------------
    sc = metrics.scorecard(bundle, a)
    scp = metrics.scorecard(prev_bundle, a)
    eff = metrics.efficiency(bundle, a)

    st.subheader("Blended scorecard")
    st.caption("Period-over-period vs the preceding equal-length window.")
    k = st.columns(6)
    k[0].metric("Ad spend", compact_money(sc["spend"], currency),
                delta_str(sc["spend"], scp["spend"], "money"), delta_color="inverse")
    k[1].metric("MER", ratio(sc["mer"]), delta_str(sc["mer"], scp["mer"], "ratio"))
    k[2].metric("CAC (blended)", money(sc["cac"], currency, 2),
                delta_str(sc["cac"], scp["cac"], "money"), delta_color="inverse")
    k[3].metric("nCAC (new cust.)", money(sc["ncac"], currency, 2),
                delta_str(sc["ncac"], scp["ncac"], "money"), delta_color="inverse")
    k[4].metric("CAC payback", f'{sc["payback_months"]:.1f} mo' if not math.isnan(sc["payback_months"]) else "—",
                delta_str(sc["payback_months"], scp["payback_months"], "months"), delta_color="inverse")
    k[5].metric("Returning-order share", pct(sc["repeat_90d"]),
                delta_str(sc["repeat_90d"], scp["repeat_90d"], "pct"))

    # -- trend ---------------------------------------------------------------
    ts = metrics.mer_timeseries(bundle)
    t1, t2 = st.columns([3, 2])
    with t1:
        st.markdown("**Ad spend vs store revenue**")
        c = chart_spend_vs_revenue(ts, currency)
        st.altair_chart(c, width="stretch") if c is not None else st.info("No time-series data.")
    with t2:
        st.markdown("**MER over time**")
        c = chart_mer(ts)
        st.altair_chart(c, width="stretch") if c is not None else st.info("No MER data.")

    # -- section tabs ---------------------------------------------------------
    tabs = st.tabs(["① Efficiency / Spend", "② Funnel / Conversion",
                    "③ Retention / Quality", "④ Influencer",
                    "★ Source / creative breakdown", "◆ Channel split",
                    "📸 Instagram"])

    # ---- Efficiency ----
    with tabs[0]:
        c = st.columns(4)
        c[0].metric("Spend", money(eff["spend"], currency))
        c[1].metric("Impressions", num(eff["impressions"]))
        c[2].metric("CPM", money(eff["cpm"], currency, 2))
        c[3].metric("CPC", money(eff["cpc"], currency, 2))
        c = st.columns(4)
        c[0].metric("CTR", pct(eff["ctr"], 2))
        c[1].metric("Platform ROAS", ratio(eff["platform_roas"]))
        c[2].metric("MER", ratio(eff["mer"]))
        c[3].metric("Orders", num(eff["orders"]))
        st.markdown("##### Attribution reality-check")
        rc = st.columns(3)
        rc[0].metric("Platform ROAS", ratio(eff["platform_roas"]),
                     help="Sum of platform-reported conversion value ÷ spend.")
        rc[1].metric("MER", ratio(eff["mer"]),
                     help="Total store revenue ÷ total ad spend (windowless).")
        gap = eff["attribution_gap_abs"]
        rc[2].metric("MER − ROAS gap", ratio(gap) if not math.isnan(gap) else "—",
                     help="Positive = platforms under-claim vs blended reality; "
                          "negative = platforms over-claim (double-counting / view-through).")
        if eff["store_revenue_is_fallback"]:
            st.warning("Store revenue unavailable (Shopify not on Windsor) — MER uses "
                       "platform-attributed revenue as a fallback, so MER ≈ ROAS here.")
        cc = st.columns(3)
        cc[0].metric("CAC (per order)", money(eff["cac"], currency, 2))
        cc[1].metric("nCAC (per new customer)", money(eff["ncac"], currency, 2),
                     help="Spend ÷ estimated new customers (orders × GA4 new-customer share).")
        cc[2].metric("Est. new-customer share", pct(eff["new_share"]))

    # ---- Funnel ----
    with tabs[1]:
        f = metrics.funnel(bundle, a)
        if not f.get("available"):
            st.info("GA4 funnel data unavailable for this range.")
        else:
            fc = st.columns(4)
            fc[0].metric("Add-to-cart rate", pct(f["atc_rate"]))
            fc[1].metric("Checkout-initiation rate", pct(f["checkout_rate"]))
            fc[2].metric("Conversion rate", pct(f["conversion_rate"]))
            fc[3].metric("Checkout → purchase", pct(f["checkout_to_purchase"]))
            left, right = st.columns([3, 2])
            with left:
                st.markdown("**Funnel volume (GA4)**")
                st.altair_chart(chart_funnel(f), width="stretch")
            with right:
                st.markdown("**Converted sessions: new vs returning**")
                nr = pd.DataFrame({
                    "Segment": ["New", "Returning"],
                    "Transactions": [f["new_txn"], f["returning_txn"]],
                })
                st.altair_chart(
                    alt.Chart(nr).mark_bar(cornerRadiusEnd=4, size=40).encode(
                        x=alt.X("Segment:N", title=None),
                        y=alt.Y("Transactions:Q", title=None, axis=alt.Axis(format="~s")),
                        color=alt.Color("Segment:N", scale=alt.Scale(range=[C_BLUE, C_AQUA]),
                                        legend=None),
                        tooltip=["Segment", alt.Tooltip("Transactions:Q", format=",.0f")],
                    ).properties(height=200), width="stretch")
            st.markdown("##### Landing-page CVR by creative/influencer")
            st.caption("Click→purchase CVR (proxy for LP CVR). Isolates creative from "
                       "targeting only insofar as clicks are comparable across placements.")
            cvr = metrics.creative_cvr(bundle)
            if cvr.empty:
                st.info("No campaign-level data.")
            else:
                show = cvr[["platform", "brand", "campaign", "spend", "clicks",
                            "purchases", "click_cvr", "roas"]].head(20).copy()
                st.dataframe(
                    show, width="stretch", hide_index=True,
                    column_config={
                        "spend": st.column_config.NumberColumn("Spend", format="%.0f"),
                        "purchases": st.column_config.NumberColumn("Orders", format="%.0f"),
                        "click_cvr": st.column_config.NumberColumn("Click CVR", format="%.2f%%"),
                        "roas": st.column_config.NumberColumn("ROAS", format="%.2f"),
                    })

    # ---- Retention ----
    with tabs[2]:
        r = metrics.retention(bundle, a)
        st.caption("Supplements are repeat-driven — this section is weighted, but true "
                   "cohort repeat needs order-level Shopify data (order_date + customer_id).")
        rc = st.columns(4)
        lc_txt = ratio(r["ltv_cac"])
        rc[0].metric("LTV : CAC", lc_txt, help="Gross LTV ÷ nCAC. LTV is gross — see caveat; "
                     "do not read as fully-loaded ROI.")
        rc[1].metric("Gross-margin LTV : nCAC", ratio(r["gm_ltv_cac"]))
        pv = r["payback_months"]
        rc[2].metric("CAC payback", f"{pv:.1f} mo" if not math.isnan(pv) else "—",
                     delta="⚠ over threshold" if r["payback_red"] else None,
                     delta_color="inverse")
        rc[3].metric("Contribution margin %", pct(r["cm_margin_pct"]))
        cc = st.columns(4)
        cc[0].metric("CM2 / customer", money(r["cm2_per_customer"], currency, 2),
                     help="Net AOV − COGS − payment fees.")
        cc[1].metric("CM3 / customer", money(r["cm3_per_customer"], currency, 2),
                     help="CM2 − shipping/fulfilment − acquisition cost (nCAC).")
        cc[2].metric("Subscribe & Save take-rate", pct(r["subscription_take_rate"]),
                     help="Assumption input — no subscription connector wired.")
        cc[3].metric("Returning-order share (proxy)", pct(r["returning_order_share_proxy"]),
                     help="GA4 returning-vs-new transaction share — proxy for repeat "
                          "behaviour pending order-level cohorts.")
        st.markdown(f"##### {a['repeat_window_days']}-day repeat rate by acquisition source")
        st.info("Requires Shopify **order-level** data (first-order cohort keyed on "
                "customer_id + order_date). Not available from the connected sources — "
                "connect Shopify to Windsor (or add order export) to populate this. "
                "The source table (★) shows a GA4-derived repeat proxy in the meantime.")

    # ---- Influencer ----
    with tabs[3]:
        inf = metrics.influencer(bundle, a)
        st.caption("No GRIN/Awin/promo-code connector on this account — boosted organic "
                   "posts are used as the influencer/creative proxy.")
        ic = st.columns(4)
        ic[0].metric("Deliverables (boosted posts)", num(inf["n_deliverables"]))
        ic[1].metric("Influencer spend", money(inf["spend"], currency))
        ic[2].metric("Cost / deliverable", money(inf["cost_per_deliverable"], currency, 2))
        ic[3].metric("Effective CPM", money(inf["effective_cpm"], currency, 2))
        ic2 = st.columns(3)
        ic2[0].metric("Promo/affiliate orders", num(inf["promo_attributed_orders"]),
                      help="Primary influencer signal — needs a promo-code/affiliate feed.")
        ic2[1].metric("Promo/affiliate revenue", money(inf["promo_attributed_revenue"], currency))
        ic2[2].metric("Promo source connected", "No")
        st.markdown("##### Incrementality proxy — MER lift vs baseline")
        incr = metrics.incrementality_proxy(bundle, a)
        if not incr.get("available"):
            st.info("Not enough time-series data for an incrementality estimate.")
        else:
            xc = st.columns(3)
            xc[0].metric("Baseline MER", ratio(incr["baseline_mer"]), help=incr["basis"])
            xc[1].metric("Flight MER", ratio(incr["flight_mer"]))
            xc[2].metric("MER lift", pct(incr["lift_pct"]),
                         help="Estimate — under-credits true incremental lift.")

    # ---- Source / creative breakdown (headline cut) ----
    with tabs[4]:
        st.markdown("**CAC payback & repeat rate by source / creative** — the "
                    "most decision-useful cut. Sortable; click a column header.")
        sb = metrics.source_breakdown(bundle, a)
        if sb.empty:
            st.info("No campaign-level data available.")
        else:
            st.dataframe(
                sb, width="stretch", hide_index=True, height=520,
                column_config={
                    "platform": "Platform", "brand": "Brand", "campaign": "Source / creative",
                    "type": "Type",
                    "spend": st.column_config.NumberColumn("Spend", format="%.0f"),
                    "clicks": st.column_config.NumberColumn("Clicks", format="%.0f"),
                    "orders": st.column_config.NumberColumn("Orders", format="%.0f"),
                    "revenue": st.column_config.NumberColumn("Attr. rev", format="%.0f"),
                    "roas": st.column_config.NumberColumn("ROAS", format="%.2f"),
                    "click_cvr": st.column_config.NumberColumn("Click CVR", format="%.2f%%"),
                    "cac": st.column_config.NumberColumn("CAC", format="%.2f"),
                    "cac_payback_months": st.column_config.NumberColumn("CAC payback (mo)", format="%.1f"),
                    "repeat_90d_proxy": st.column_config.NumberColumn(
                        f"Repeat {a['repeat_window_days']}d (proxy)", format="%.2f%%"),
                })
            st.caption("`Repeat …d (proxy)` is a blended GA4 returning-order share applied "
                       "across rows — a placeholder until per-source order-level cohorts are "
                       "available. `CAC` uses platform-attributed orders; `CAC payback` uses "
                       "the sidebar unit-economics assumptions.")

    # ---- Channel split ----
    with tabs[5]:
        st.markdown("**Channel split** — GA4 default channel grouping.")
        cb = metrics.channel_breakdown(bundle)
        if cb.empty:
            st.info("GA4 channel data unavailable.")
        else:
            st.caption("Reflects the GA4 pull window (~30 days), independent of the "
                       "selected range. Revenue is GA4-attributed, so it differs from "
                       "Shopify store revenue (last-touch vs booked).")
            left, right = st.columns([2, 3])
            with left:
                tot_sessions = cb["sessions"].sum()
                tot_rev = cb["revenue"].sum()
                top = cb.iloc[0]
                m = st.columns(2)
                m[0].metric("Channels", num(len(cb)))
                m[1].metric("Top channel by revenue", str(top["channel"]))
                m2 = st.columns(2)
                m2[0].metric("Sessions (all channels)", num(tot_sessions))
                m2[1].metric("GA4 revenue", money(tot_rev, currency))
            with right:
                st.altair_chart(chart_channel(cb, currency), width="stretch")
            show = cb[["channel", "sessions", "atc_rate", "cvr", "transactions",
                       "revenue", "rev_share", "new_share"]].copy()
            st.dataframe(
                show, width="stretch", hide_index=True,
                column_config={
                    "channel": "Channel",
                    "sessions": st.column_config.NumberColumn("Sessions", format="%.0f"),
                    "atc_rate": st.column_config.NumberColumn("ATC rate", format="%.2f%%"),
                    "cvr": st.column_config.NumberColumn("CVR", format="%.2f%%"),
                    "transactions": st.column_config.NumberColumn("Orders", format="%.0f"),
                    "revenue": st.column_config.NumberColumn("Revenue", format="%.0f"),
                    "rev_share": st.column_config.NumberColumn("Rev share", format="%.1f%%"),
                    "new_share": st.column_config.NumberColumn("New-visitor share", format="%.1f%%"),
                })
            st.caption("`ATC rate`, `CVR`, `rev share`, `new-visitor share` are fractions "
                       "rendered as %. Paid Social converts far below Cross-network / Paid "
                       "Search here — a creative/landing-page signal, not just spend.")

    # ---- Instagram ----
    with tabs[6]:
        st.markdown("**Instagram insights** — organic account health, paid creative "
                    "performance, and per-creator promo-code attribution.")
        st.caption("Organic per-account insights (Windsor `instagram`), paid boosted posts "
                   "(the creative proxy), and per-creator attribution from Shopify discount "
                   "codes. Creators are paid a fixed fee (editable below).")

        st.markdown("##### Organic account insights")
        io = metrics.instagram_organic(bundle)
        if io.empty:
            st.info("Instagram organic data unavailable.")
        else:
            st.caption("Reach + engagement are 90-day totals; new followers is 30-day "
                       "(the field's max window).")
            show = io[["account", "brand", "reach", "new_followers", "likes", "comments",
                       "shares", "total_interactions", "engagement_rate"]].copy()
            st.dataframe(
                show, width="stretch", hide_index=True,
                column_config={
                    "account": "Account", "brand": "Brand",
                    "reach": st.column_config.NumberColumn("Reach (90d)", format="%.0f"),
                    "new_followers": st.column_config.NumberColumn("New followers (30d)", format="%.0f"),
                    "likes": st.column_config.NumberColumn("Likes", format="%.0f"),
                    "comments": st.column_config.NumberColumn("Comments", format="%.0f"),
                    "shares": st.column_config.NumberColumn("Shares", format="%.0f"),
                    "total_interactions": st.column_config.NumberColumn("Interactions", format="%.0f"),
                    "engagement_rate": st.column_config.NumberColumn("Eng. rate / reach", format="%.2f%%"),
                })

        st.markdown("##### Paid Instagram creatives (boosted posts)")
        ic = metrics.instagram_creatives(bundle)
        if ic.empty:
            st.info("No boosted-post campaigns in the pull window.")
        else:
            st.caption("Per-post spend, delivery and attributed outcome. Boosted posts "
                       "here optimise for traffic/engagement (high clicks, near-zero "
                       "attributed purchases) — treat as upper-funnel creative tests.")
            show = ic[["post", "brand", "spend", "impressions", "clicks", "ctr",
                       "cpc", "cpm", "purchases", "revenue", "roas"]].copy()
            st.dataframe(
                show, width="stretch", hide_index=True, height=360,
                column_config={
                    "post": "Post / creative", "brand": "Brand",
                    "spend": st.column_config.NumberColumn("Spend", format="%.0f"),
                    "impressions": st.column_config.NumberColumn("Impr.", format="%.0f"),
                    "clicks": st.column_config.NumberColumn("Clicks", format="%.0f"),
                    "ctr": st.column_config.NumberColumn("CTR", format="%.2f%%"),
                    "cpc": st.column_config.NumberColumn("CPC", format="%.2f"),
                    "cpm": st.column_config.NumberColumn("eCPM", format="%.2f"),
                    "purchases": st.column_config.NumberColumn("Orders", format="%.0f"),
                    "revenue": st.column_config.NumberColumn("Attr. rev", format="%.0f"),
                    "roas": st.column_config.NumberColumn("ROAS", format="%.2f"),
                })

        st.markdown("##### Promo-code attribution per influencer")
        if bundle.influencer_codes.empty:
            st.info("No discount-code data. In demo mode this is bundled; in live mode "
                    "add `SHOPIFY_SHOP` + `SHOPIFY_ACCESS_TOKEN` to secrets so the Shopify "
                    "Admin API can supply per-code orders/revenue.")
        else:
            # Creators are paid a FIXED FEE per creator (not a commission). Seed each
            # from the sidebar default (or config overrides); editable per creator.
            roster = bundle.influencer_codes
            roster = roster[roster["category"] == "Influencer"][["influencer", "code"]].copy()
            roster["fixed_fee"] = roster["code"].map(
                lambda c: float(config.CREATOR_FIXED_FEES.get(c, a["default_creator_fee"])))
            with st.expander("Fixed fee per creator (flat fee for the period — editable)"):
                st.caption("Creators are paid a fixed fee, not a commission. Defaults to the "
                           "sidebar value; edit a row to your real deal and the scorecard + "
                           "table recompute.")
                edited = st.data_editor(
                    roster, hide_index=True, width="stretch", key="creator_fees",
                    disabled=["influencer", "code"],
                    column_config={
                        "influencer": "Creator", "code": "Code",
                        "fixed_fee": st.column_config.NumberColumn(
                            f"Fixed fee ({currency})", min_value=0.0, step=25.0, format="%.0f"),
                    })
            fee_map = dict(zip(edited["code"], edited["fixed_fee"]))

            codes = metrics.influencer_code_attribution(bundle, a, fee_map)
            summ = metrics.influencer_code_summary(codes)
            if summ.get("available"):
                st.caption("Blended across influencer codes. Discount cost is real "
                           "(Shopify); creator cost is the fixed fee per creator (above).")
                sc = st.columns(6)
                sc[0].metric("Creators", num(summ["creators"]))
                sc[1].metric("Attributed revenue", compact_money(summ["revenue"], currency))
                sc[2].metric("Orders", num(summ["orders"]))
                sc[3].metric("Blended ROAS", ratio(summ["roas"]),
                             help="Attributed revenue ÷ (discount + fixed creator fees).")
                sc[4].metric("CAC / new cust.", money(summ["cac_new"], currency, 2))
                sc[5].metric("New-customer share",
                             pct(summ["new_customers"] / summ["orders"] if summ["orders"] else float("nan")))
            infl = codes[codes["category"] == "Influencer"].copy()
            st.caption("Per-creator table — sortable. `New %` uses customer order-count at "
                       "query time (proxy). `Creator fee` is the fixed fee; `CAC` and `ROAS` "
                       "fold in fee + discount; `discount` and revenue are real.")
            show = infl[["influencer", "code", "orders", "new_customers", "new_rate",
                         "total_sales", "aov", "discount", "discount_pct",
                         "creator_fee", "roas", "cac_new", "contribution"]].copy()
            st.dataframe(
                show, width="stretch", hide_index=True, height=460,
                column_config={
                    "influencer": "Creator", "code": "Code",
                    "orders": st.column_config.NumberColumn("Orders", format="%.0f"),
                    "new_customers": st.column_config.NumberColumn("New cust.", format="%.0f"),
                    "new_rate": st.column_config.NumberColumn("New %", format="%.0f%%"),
                    "total_sales": st.column_config.NumberColumn("Revenue", format="%.0f"),
                    "aov": st.column_config.NumberColumn("AOV", format="%.2f"),
                    "discount": st.column_config.NumberColumn("Discount €", format="%.0f"),
                    "discount_pct": st.column_config.NumberColumn("Disc %", format="%.1f%%"),
                    "creator_fee": st.column_config.NumberColumn("Creator fee €", format="%.0f"),
                    "roas": st.column_config.NumberColumn("ROAS", format="%.2f"),
                    "cac_new": st.column_config.NumberColumn("CAC (new)", format="%.2f"),
                    "contribution": st.column_config.NumberColumn("Contribution €", format="%.0f"),
                })
            other = codes[codes["category"] != "Influencer"]
            if not other.empty:
                by_cat = (other.groupby("category")
                          .agg(codes=("code", "nunique"), orders=("orders", "sum"),
                               revenue=("total_sales", "sum"), discount=("discount", "sum"))
                          .reset_index())
                with st.expander("Non-influencer codes (promo / auto-loyalty) for context"):
                    st.dataframe(
                        by_cat, width="stretch", hide_index=True,
                        column_config={
                            "category": "Category",
                            "codes": st.column_config.NumberColumn("Codes", format="%.0f"),
                            "orders": st.column_config.NumberColumn("Orders", format="%.0f"),
                            "revenue": st.column_config.NumberColumn("Revenue", format="%.0f"),
                            "discount": st.column_config.NumberColumn("Discount €", format="%.0f"),
                        })
            st.caption("⚠ Code-based attribution under-credits true lift (view-through, "
                       "creators who drive branded search / direct) and can overlap paid "
                       "social. Treat as a floor, not full incrementality.")

    st.divider()
    st.caption("Built on Windsor.ai (Meta, Google, TikTok, GA4, Instagram) + Shopify. Assumptions are "
               "editable in the sidebar and are not business truth. Data-access layer is "
               "swappable (windsor_client.py); KPI math is in metrics.py.")


if __name__ == "__main__":
    main()
