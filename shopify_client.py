"""Shopify data access (direct Admin API).

Shopify is reached DIRECTLY via the Admin GraphQL API — not through Windsor. A
deployed app can't call the Shopify MCP (that is agent-side only), so live Shopify
data uses a shop domain + Admin API access token from st.secrets/env. The demo
snapshot was built from the same data pulled via the Shopify MCP at build time.

Provides per-discount-code sales aggregation for influencer/promo attribution.
Returns an empty frame (never raises) when credentials are absent so the app
degrades to the snapshot / surfaces the gap.
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Optional

import pandas as pd
import requests

try:
    import streamlit as st
except Exception:  # allow use outside streamlit
    st = None

import config

API_VERSION = "2025-01"


def get_credentials() -> tuple[Optional[str], Optional[str]]:
    """(shop_domain, access_token) from st.secrets or env; either may be None."""
    shop = token = None
    if st is not None:
        try:
            shop = st.secrets.get("SHOPIFY_SHOP")
            token = st.secrets.get("SHOPIFY_ACCESS_TOKEN")
        except Exception:
            pass
    shop = shop or os.environ.get("SHOPIFY_SHOP")
    token = token or os.environ.get("SHOPIFY_ACCESS_TOKEN")
    return shop, token


def _gql(shop: str, token: str, query: str, variables: dict) -> dict:
    resp = requests.post(
        f"https://{shop}/admin/api/{API_VERSION}/graphql.json",
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
        json={"query": query, "variables": variables}, timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


_ORDERS_Q = """
query Orders($q: String!, $cursor: String) {
  orders(first: 250, query: $q, after: $cursor, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      discountCodes
      currentSubtotalPriceSet { shopMoney { amount } }
      totalDiscountsSet { shopMoney { amount } }
      customer { numberOfOrders }
    }
  }
}
"""


def fetch_discount_code_sales(date_from: str, date_to: str,
                              max_pages: int = 40) -> pd.DataFrame:
    """Aggregate orders by discount code into the influencer_codes schema.

    Returning is proxied by customer.numberOfOrders > 1 (current count — the same
    proxy the UI flags). Empty frame on missing creds or any transport error."""
    shop, token = get_credentials()
    if not shop or not token:
        return pd.DataFrame()

    q = f"created_at:>={date_from} created_at:<={date_to}"
    agg = defaultdict(lambda: dict(orders=0, net=0.0, discount=0.0, returning=0))
    cursor = None
    try:
        for _ in range(max_pages):
            data = _gql(shop, token, _ORDERS_Q, {"q": q, "cursor": cursor})
            conn = data.get("data", {}).get("orders", {})
            for o in conn.get("nodes", []):
                codes = o.get("discountCodes") or [""]
                code = codes[0] if codes else ""
                net = float(o.get("currentSubtotalPriceSet", {}).get("shopMoney", {}).get("amount", 0) or 0)
                disc = float(o.get("totalDiscountsSet", {}).get("shopMoney", {}).get("amount", 0) or 0)
                cust = o.get("customer") or {}
                is_returning = int(cust.get("numberOfOrders", 1) or 1) > 1
                a = agg[code]
                a["orders"] += 1
                a["net"] += net
                a["discount"] += disc
                a["returning"] += 1 if is_returning else 0
            page = conn.get("pageInfo", {})
            if not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")
    except requests.RequestException:
        return pd.DataFrame()

    rows = []
    for code, a in agg.items():
        cat, name = config.classify_code(code)
        if cat == "Uncoded":
            continue
        gross = a["net"] + a["discount"]
        rows.append(dict(
            code=code, category=cat, influencer=name or "",
            orders=a["orders"], gross_sales=gross, discount=a["discount"],
            net_sales=a["net"], total_sales=a["net"],  # total≈net (pre tax/ship)
            returning_customers=a["returning"],
        ))
    return pd.DataFrame(rows)
