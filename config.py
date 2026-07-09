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

# --- Influencer / promo-code attribution ---------------------------------------
# Commission paid to creators, modelled as % of their code's attributed revenue
# (PLACEHOLDER — replace per-creator in INFLUENCER_ROSTER when you have real deals).
DEFAULT_INFLUENCER_COMMISSION_PCT = 15.0

# Roster maps a Shopify discount code -> creator display name. Extend as you
# onboard creators; codes not listed are auto-classified (see classify_code).
INFLUENCER_ROSTER = {
    "ICHHASSEVEGANER": "@ichhasseveganer",
    "LEONIE10": "Leonie",
    "DISPENSAVEG10": "Dispensa Veg",
    "ILARIA10": "Ilaria",
    "MARIA10": "Maria",
    "LOLA10": "Lola",
    "LABDOMESTICO10": "Lab Domestico",
    "SARADESIDERIA10": "Sara Desideria",
    "IRINA10": "Irina",
    "CLARA10": "Clara",
    "HELLOFABIANA20": "Fabiana",
    "CARLOTTA10": "Carlotta",
    "SARA10": "Sara",
    "NAWROT10": "Nawrot",
    "ANNIKA10": "Annika",
    "ANGIE": "Angie",
    "NICOL10": "Nicol",
    "EEFKE10": "Eefke",
    "EVELYN10": "Evelyn",
    "ANDREA10": "Andrea",
    "FABIA10": "Fabia",
}

# Store-wide promo codes (NOT influencer). Everything auto-generated
# (loyalty/gift) is detected by prefix in classify_code.
PROMO_CODES = {
    "VEGANCHECK10", "VEGANSPAREN10", "WELCOMEBACK20", "WELCOME15",
    "MOM10", "APOLOGY", "NEWMORINGA",
}


def classify_code(code: str):
    """Return (category, influencer_name) for a discount code.

    category in {Influencer, Promo, Auto/Loyalty, Uncoded, Other}. Personal
    name+number codes not yet in the roster are inferred as Influencer so new
    creators show up before the roster is updated."""
    import re
    c = (code or "").strip()
    if c == "" or c.lower() == "custom discount":
        return "Uncoded", None
    if c in INFLUENCER_ROSTER:
        return "Influencer", INFLUENCER_ROSTER[c]
    if c in PROMO_CODES:
        return "Promo", None
    if c.startswith("PURE") or c.startswith("10GIFT") or re.fullmatch(r"[A-Z0-9]{8}", c):
        return "Auto/Loyalty", None
    m = re.fullmatch(r"([A-Z][A-Za-z]+?)\d{1,2}", c)  # NAME + number -> inferred creator
    if m:
        return "Influencer", m.group(1).title()
    return "Other", None

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
