"""Configuration, assumption defaults, and the cached Windsor field map.

Everything here is a find-and-replaceable PLACEHOLDER. The dashboard surfaces
every value below as a sidebar input so an analyst can lock real numbers without
touching code. Nothing here is a claim about the business — they are defaults.
"""
from __future__ import annotations

# --- Reporting basis (asked, not assumed — placeholder defaults from the shop) ---
# The connected Shopify store reports in EUR / Europe-Berlin; used as the default
# only. Both are editable in the sidebar.
DEFAULT_CURRENCY = "EUR"
DEFAULT_TIMEZONE = "Europe/Berlin"

CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF "}

# --- Attribution ---
# CAC attribution window (days, click-based). Platform ROAS uses each platform's
# own default attribution; MER is windowless (total revenue / total spend).
DEFAULT_CAC_ATTRIBUTION_DAYS = 7

# --- Unit economics (PLACEHOLDERS — replace with finance's real figures) ---
DEFAULT_COGS_PCT = 32.0          # blended COGS as % of net revenue
DEFAULT_PAYMENT_FEE_PCT = 2.4    # payment processing % of gross
DEFAULT_SHIPPING_PER_ORDER = 4.50  # fulfilment + shipping, per order, in currency
DEFAULT_AVG_ORDER_MARGIN_PCT = None  # if set, overrides COGS-derived margin

# --- LTV / retention (PLACEHOLDERS) ---
DEFAULT_AVG_CUSTOMER_LTV = 165.0   # 12-month gross LTV per acquired customer
DEFAULT_LTV_WINDOW_MONTHS = 12
DEFAULT_PAYBACK_RED_MONTHS = 3.0   # flag CAC payback > this many months
DEFAULT_REPEAT_WINDOW_DAYS = 90    # repeat-rate window (first-order cohort)
DEFAULT_SUBSCRIPTION_TAKE_RATE = 18.0  # % of first orders on Subscribe & Save

# --- Incrementality ---
# MER baseline window for the influencer incrementality proxy (ISO dates or None
# to use the first 14 days of the selected range as the baseline).
DEFAULT_MER_BASELINE_FROM = None
DEFAULT_MER_BASELINE_TO = None

# --- Windsor.ai connectors in scope --------------------------------------------
# Connector slugs as returned by Windsor get_connectors.
WINDSOR_CONNECTORS = {
    "meta": "facebook",       # Meta Ads (Facebook & Instagram)
    "google": "google_ads",
    "tiktok": "tiktok",
    "ga4": "googleanalytics4",
}

# Cached FIELD MAP -- resolved via Windsor `get_fields` (do NOT guess field IDs).
# Field IDs differ per connector (e.g. Meta purchases = actions_omni_purchase,
# Google = conversions). windsor_client normalises them to a common schema.
FIELD_MAP = {
    "facebook": {
        "dims": ["date", "account_name", "campaign"],
        "metrics": ["spend", "impressions", "clicks",
                    "actions_omni_purchase", "action_values_omni_purchase"],
        "purchases_field": "actions_omni_purchase",
        "revenue_field": "action_values_omni_purchase",
    },
    "google_ads": {
        "dims": ["date", "account_name", "campaign"],
        "metrics": ["spend", "impressions", "clicks",
                    "conversions", "conversions_value"],
        "purchases_field": "conversions",
        "revenue_field": "conversions_value",
    },
    "tiktok": {
        "dims": ["date", "account_name", "campaign"],
        "metrics": ["spend", "impressions", "clicks", "conversions"],
        "purchases_field": "conversions",
        "revenue_field": None,  # not exposed by this connector
    },
    "googleanalytics4": {
        "dims": ["date", "default_channel_group", "new_vs_returning"],
        "metrics": ["sessions", "add_to_carts", "checkouts", "transactions",
                    "totalrevenue", "newusers", "totalusers"],
    },
}

# Data freshness
DEFAULT_CACHE_TTL_SECONDS = 3600  # 1h; user-refreshable via a button

DATE_PRESETS = {
    "Last 7 days": 7,
    "Last 14 days": 14,
    "Last 30 days": 30,
    "Last 60 days": 60,
    "Last 90 days": 90,
}
