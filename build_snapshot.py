"""Build sample_data/snapshot.json from raw connector exports.

This is a DEV/PROVENANCE tool, not part of the running app. It normalises the
raw JSON that was pulled live from the Windsor.ai MCP (Meta Ads, Google Ads,
TikTok Ads, GA4) and the Shopify MCP (ShopifyQL `sales`) on 2026-07-09, covering
2026-04-10 .. 2026-07-09, into the single normalised schema the app consumes.

The running app pulls the SAME schema live from Windsor (see windsor_client.py);
this snapshot is only the offline/demo fallback used when no WINDSOR_API_KEY is
configured, so the dashboard renders out-of-the-box on Streamlit Community Cloud.

Raw exports are expected in RAW_DIR (the session scratchpad by default; override
with SNAPSHOT_RAW_DIR). Run:  python build_snapshot.py
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

RAW_DIR = os.environ.get(
    "SNAPSHOT_RAW_DIR",
    "/tmp/claude-0/-home-user-socialmedia/1719d471-07b1-5a86-a449-53210083bedb/scratchpad",
)
OUT = os.path.join(os.path.dirname(__file__), "sample_data", "snapshot.json")

DATE_FROM, DATE_TO = "2026-04-10", "2026-07-09"


def _load(name):
    with open(os.path.join(RAW_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def brand_of(account: str) -> str:
    return "wowtamins" if "wowtamins" in account.lower() else "Vegavero"


def is_influencer_campaign(name: str) -> bool:
    # Boosted organic/creator posts are the closest available influencer/creative
    # signal on this account (no GRIN/Awin connector). Labelled as a proxy in-app.
    return name.strip().lower().startswith("instagram post")


def build_ads_daily():
    rows = []
    for r in _load("meta_daily.json"):
        rows.append({
            "date": r["date"], "platform": "Meta", "account": r["account_name"],
            "brand": brand_of(r["account_name"]), "spend": r["spend"],
            "impressions": r["impressions"], "clicks": r["clicks"],
            "purchases": r["actions_omni_purchase"],
            "revenue": r["action_values_omni_purchase"],
        })
    for r in _load("google_daily.json"):
        rows.append({
            "date": r["date"], "platform": "Google", "account": r["account_name"],
            "brand": brand_of(r["account_name"]), "spend": r["spend"],
            "impressions": r["impressions"], "clicks": r["clicks"],
            "purchases": r["conversions"], "revenue": r["conversions_value"],
        })
    return rows


def build_ads_campaigns():
    rows = []
    for r in _load("meta_campaigns.json"):
        rows.append({
            "platform": "Meta", "account": r["account_name"],
            "brand": brand_of(r["account_name"]), "campaign": r["campaign"],
            "is_influencer": is_influencer_campaign(r["campaign"]),
            "spend": r["spend"], "impressions": r["impressions"], "clicks": r["clicks"],
            "purchases": r["actions_omni_purchase"],
            "revenue": r["action_values_omni_purchase"],
        })
    for r in _load("google_campaigns.json"):
        rows.append({
            "platform": "Google", "account": r["account_name"],
            "brand": brand_of(r["account_name"]), "campaign": r["campaign"],
            "is_influencer": is_influencer_campaign(r["campaign"]),
            "spend": r["spend"], "impressions": r["impressions"], "clicks": r["clicks"],
            "purchases": r["conversions"], "revenue": r["conversions_value"],
        })
    return rows


def build_ga4_daily():
    # Two GA4 properties share each date; sum them into a blended daily row.
    agg = defaultdict(lambda: defaultdict(float))
    for r in _load("ga4_daily.json"):
        d = agg[r["date"]]
        for k in ("sessions", "add_to_carts", "checkouts", "transactions",
                  "totalrevenue", "newusers", "totalusers"):
            d[k] += r[k]
    out = []
    for date in sorted(agg):
        d = agg[date]
        out.append({
            "date": date, "sessions": int(d["sessions"]),
            "add_to_carts": int(d["add_to_carts"]), "checkouts": int(d["checkouts"]),
            "transactions": int(d["transactions"]), "revenue": round(d["totalrevenue"], 2),
            "newusers": int(d["newusers"]), "totalusers": int(d["totalusers"]),
        })
    return out


def build_ga4_channel():
    agg = defaultdict(lambda: defaultdict(float))
    for r in _load("ga4_channel.json"):
        d = agg[r["default_channel_group"]]
        for k in ("sessions", "add_to_carts", "checkouts", "transactions",
                  "totalrevenue", "newusers", "totalusers"):
            d[k] += r[k]
    out = []
    for ch, d in agg.items():
        out.append({
            "channel": ch, "sessions": int(d["sessions"]),
            "add_to_carts": int(d["add_to_carts"]), "checkouts": int(d["checkouts"]),
            "transactions": int(d["transactions"]), "revenue": round(d["totalrevenue"], 2),
            "newusers": int(d["newusers"]), "totalusers": int(d["totalusers"]),
        })
    return sorted(out, key=lambda x: -x["sessions"])


def build_ga4_new_returning():
    agg = defaultdict(lambda: defaultdict(float))
    for r in _load("ga4_new_returning.json"):
        seg = r["new_vs_returning"]
        seg = seg if seg in ("new", "returning") else "unknown"
        d = agg[seg]
        for k in ("sessions", "transactions", "totalrevenue"):
            d[k] += r[k]
    return [{"segment": s, "sessions": int(agg[s]["sessions"]),
             "transactions": int(agg[s]["transactions"]),
             "revenue": round(agg[s]["totalrevenue"], 2)} for s in agg]


def build_shopify_daily():
    out = []
    for total, in_ in [(r, r) for r in _load("shopify_daily.json")]:
        date, total_sales, net_sales, orders, aov = in_
        out.append({"date": date, "total_sales": float(total_sales),
                    "net_sales": float(net_sales), "orders": int(orders),
                    "aov": float(aov)})
    return out


def build_shopify_products():
    return [{"product": p, "total_sales": float(ts), "items": int(items),
             "orders": int(orders)}
            for p, ts, items, orders in _load("shopify_products.json")]


def build_instagram_accounts():
    """Instagram organic per-account insights (Windsor `instagram` connector).
    Engagement + reach are 90-day totals; new_followers is 30-day (the field's
    max window). No GRIN/Awin/promo-code connector, so there is no per-influencer
    or per-code cut — this is the account/creative-level organic signal."""
    return [
        {"account": "vegavero.de", "brand": "Vegavero", "reach": 607225,
         "new_followers": 1008, "likes": 3071, "comments": 153, "shares": 369,
         "total_interactions": 4888},
        {"account": "wowtamins.de", "brand": "wowtamins", "reach": 1208280,
         "new_followers": 495, "likes": 7014, "comments": 554, "shares": 455,
         "total_interactions": 9991},
        {"account": "vegavero.italia", "brand": "Vegavero", "reach": 327325,
         "new_followers": 953, "likes": 12207, "comments": 214, "shares": 1133,
         "total_interactions": 25282},
    ]


def main():
    snapshot = {
        "meta": {
            "currency": "EUR",
            "timezone": "Europe/Berlin",
            "date_from": DATE_FROM,
            "date_to": DATE_TO,
            "shop": "Vegavero (vegavero.myshopify.com)",
            "source": "Windsor.ai MCP + Shopify MCP, pulled 2026-07-09",
            "connectors_status": {
                "Meta Ads": "connected (Vegavero, wowtamins GmbH)",
                "Google Ads": "connected (Vegavero DE, Vegavero IT, wowtamins)",
                "GA4": "connected (Vegavero, wowtamins properties)",
                "TikTok Ads": "connected — no delivery in this window",
                "Shopify": "via Shopify MCP (not a Windsor connector on this account)",
                "Influencer/affiliate (GRIN/Awin)": "not connected — using boosted-post proxy",
            },
        },
        "ads_daily": build_ads_daily(),
        "ads_campaigns": build_ads_campaigns(),
        "ga4_daily": build_ga4_daily(),
        "ga4_channel": build_ga4_channel(),
        "ga4_new_returning": build_ga4_new_returning(),
        "shopify_daily": build_shopify_daily(),
        "shopify_products": build_shopify_products(),
        "instagram_accounts": build_instagram_accounts(),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, separators=(",", ":"))
    n = {k: len(v) for k, v in snapshot.items() if isinstance(v, list)}
    print(f"Wrote {OUT}")
    print("Row counts:", n)


if __name__ == "__main__":
    main()
