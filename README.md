# Influencer & Paid-Social Performance Dashboard

A Streamlit dashboard tracking influencer and paid-social performance for a D2C
supplements brand (Shopify scope). Live data flows through **Windsor.ai**; the
audience is finance-fluent, so the UI states numbers without metric hand-holding —
but every proxy and assumption is flagged inline.

Built for the **Vegavero / wowtamins** Shopify store. Ships with a **real-data
snapshot** (pulled 2026-07-09, covering 2026-04-10 → 2026-07-09) so it runs
out-of-the-box; add a Windsor API key to switch to live.

---

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens in demo mode with the bundled snapshot. To pull live data:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml and set WINDSOR_API_KEY
streamlit run app.py            # then flip "Live Windsor.ai data" in the sidebar
```

### Deploy to Streamlit Community Cloud
Push this repo, create an app pointing at `app.py`, and add `WINDSOR_API_KEY`
under **App → Settings → Secrets**. No other configuration is needed.

---

## Architecture

Presentation is fully separated from data access and math, so the source can be
swapped (live ↔ snapshot ↔ warehouse) without touching the UI.

| File | Responsibility |
|---|---|
| `app.py` | Streamlit UI only — layout, controls, charts. No metric math. |
| `windsor_client.py` | **Data-access layer.** One function per connector, all normalised to a common schema. Live Windsor API + graceful snapshot fallback. Cached with `st.cache_data(ttl=1h)`, cleared by the sidebar refresh button. |
| `shopify_client.py` | **Shopify Admin API** access (direct, not via Windsor) for per-discount-code sales → influencer attribution. Empty frame when creds absent. |
| `metrics.py` | Pure KPI functions over a `DataBundle` + assumptions. Unit-testable, no Streamlit. |
| `config.py` | Placeholder assumption defaults + the cached Windsor **field map**. |
| `build_snapshot.py` | Dev tool that normalises raw connector exports into `sample_data/snapshot.json` (provenance for the demo data). |
| `sample_data/snapshot.json` | Real-data demo fallback. |

### Data source: Windsor.ai
The data-access layer follows the Windsor **get_connectors → get_fields →
get_data** flow. Field IDs are resolved via `get_fields` and cached in
`config.FIELD_MAP` — **never guessed at call time** — because IDs differ per
connector (Meta purchases = `actions_omni_purchase`, Google = `conversions`,
etc.); the client normalises them to one schema.

> **MCP vs API.** During development, data was pulled through the Windsor.ai
> **MCP**. A deployed Streamlit app can't reach an agent-side MCP, so the live
> path calls the Windsor.ai **connector API** (`connectors.windsor.ai`) — the
> same connector slugs, field IDs, and date semantics. That is the deployable
> equivalent of the MCP and the only live-data dependency.

**Connected via Windsor:** Meta Ads, Google Ads, TikTok Ads, GA4, Instagram.
**Shopify** is reached **directly via the Admin API** (`shopify_client.py`), not
through Windsor — sales, orders, and per-discount-code attribution. At build time
the snapshot was pulled via the Shopify MCP; the deployed app uses `SHOPIFY_SHOP`
+ `SHOPIFY_ACCESS_TOKEN`. Influencer attribution uses **per-creator Shopify
discount codes** (real on this store); a dedicated affiliate platform
(GRIN/Awin) is optional and not required. The app **surfaces any gaps** rather
than failing — see the caveats banner in-app.

---

## KPIs

**① Efficiency / Spend** — Spend, impressions, CPM, CPC, CTR; **platform ROAS vs
MER** with the gap shown explicitly as an attribution reality-check; CAC (per
order) and **nCAC** (per new customer, stripping repeat buyers via the GA4
new-customer share).

**② Funnel / Conversion** — add-to-cart / checkout-initiation / conversion rates
(GA4), landing-page CVR by creative/influencer (click→purchase proxy), new-vs-
returning split on converted sessions.

**③ Retention / Quality** *(weighted — supplements are repeat-driven)* — LTV:CAC
and gross-margin LTV:nCAC, CAC payback in months (flagged red past the sidebar
threshold), **CM2 / CM3 per acquired customer**, Subscribe & Save take-rate.
True 30/60/90-day repeat-by-source needs order-level Shopify data and is marked
unavailable with a GA4 returning-order proxy offered in the meantime.

**④ Influencer** — cost per deliverable + effective CPM, promo-code/affiliate
attributed orders & revenue (primary signal — surfaced as not-connected here),
and a **MER-lift incrementality proxy** vs a user-set baseline window.

**★ Source / creative breakdown** — the headline cut: **CAC payback and repeat
rate by source/creative**, sortable.

**◆ Channel split** — GA4 default channel grouping: sessions, ATC/CVR, revenue,
revenue share and new-visitor share per channel (revenue-by-channel chart +
sortable table). Surfaces where Paid Social converts vs Paid Search / Cross-network.

**📸 Instagram** — organic per-account insights (reach, new followers, engagement
rate; Windsor `instagram` connector), paid boosted-post creatives (per-post
spend / CTR / eCPM / attributed outcome — the influencer/creative proxy), and
**per-creator promo-code attribution** (Shopify discount codes → creator):
orders, new-customer %, revenue, real discount cost, **fixed creator fee**
(flat fee per creator, editable per row in-app — creators are paid a fixed fee,
not a commission), ROAS and CAC per creator, with promo/auto-loyalty codes
rolled up for context. Code-based attribution is flagged as a floor
(under-credits view-through lift).

---

## Assumptions (sidebar — all editable placeholders)

Currency & timezone, CAC attribution window, blended COGS %, payment-processing
%, shipping per order, avg LTV + window, CAC-payback red threshold, repeat-rate
window, Subscribe & Save take-rate, and the MER incrementality baseline window.
**None of these are business truth** — they are find-and-replaceable defaults so
finance can lock real figures without code changes.

## Caveats surfaced in the UI
- **Subscription revenue** is recognised as fulfilled, not booked upfront — LTV:CAC
  does not credit full LTV against first-order CAC (treat as a gross-margin view).
- **Influencer attribution** is promo-code/link based and under-credits true lift;
  the incrementality figure is an estimate. Boosted organic posts stand in as the
  influencer/creative proxy where no GRIN/Awin connector exists.
- **Compliance:** health / structure-function claims in creative are a regulatory
  exposure to review before scaling winners.

## Rebuilding the snapshot
The snapshot is generated from raw connector exports:
```bash
SNAPSHOT_RAW_DIR=/path/to/raw/exports python build_snapshot.py
```
