"""
Module 10b: Streamlit dashboard

Every number on every page comes from the FastAPI layer (Module 10a), which
in turn only ever reads what the EOD pipeline (Module 9) persisted. No
dashboard-only or fabricated numbers. Run with:
    streamlit run src/dashboard.py
(requires the API running: uvicorn src.api:app --port 8000)
"""

import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# API_URL is set by the host (Render) in production; falls back to localhost
# for local development.
API = os.environ.get("API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="Trading Book Risk & Controls", layout="wide")


@st.cache_data(ttl=30)
def get(path, **params):
    r = requests.get(f"{API}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def status_color(status):
    return {"RED": "#d62728", "AMBER": "#e6a817", "GREEN": "#2ca02c",
            "PASS": "#2ca02c", "WARN": "#e6a817", "FAIL": "#d62728"}.get(status, "#888")


def status_badge(status):
    return f'<span style="background:{status_color(status)};color:white;padding:2px 8px;border-radius:4px;font-size:0.8em">{status}</span>'


# Plain-English glossary shown on the "How This Works" page and reused for
# inline tooltips elsewhere - one place, not duplicated per page.
GLOSSARY = [
    ("Data Model", "Trade", "A single transaction event (price, timestamp, counterparty). Immutable once booked."),
    ("Data Model", "Instrument", "The thing being traded, defined by its own static characteristics (e.g. an option's strike is part of what defines it)."),
    ("Data Model", "Position", "The net holding in one instrument within one book, after netting all trades. This project's positions are already-netted, single-snapshot rows, not raw trades."),
    ("Data Model", "Book", "A sub-ledger within a desk where positions are grouped for P&L/risk aggregation."),
    ("Data Model", "Desk", "An organisational unit covering related products; contains multiple books."),
    ("Data Model", "Issuer", "The legal entity that issued a security. FX has no issuer."),
    ("Data Model", "Risk Factor", "The specific market observable (a price, yield, spread, volatility, or FX rate) whose movement changes a position's value."),
    ("Valuation", "Market Value", "The current worth of a position, computed as quantity x current market price (or a pricing model's output) - never an input."),
    ("Valuation", "Notional", "A reference amount (FX amount, bond face value) used to size a contract - not the same as market value."),
    ("Valuation", "Gross Exposure", "Sum of absolute market values across positions - how much capital/risk is deployed, ignoring direction."),
    ("Valuation", "Net Exposure", "Sum of signed market values - the portfolio's overall directional bet. Gross is always >= |Net|."),
    ("Risk Measurement", "VaR (Value at Risk)", "The loss level not expected to be exceeded, at a given confidence, over a given holding period. Quoted as a positive number."),
    ("Risk Measurement", "Confidence Level", "The probability the actual loss stays within VaR (e.g. 99% VaR is exceeded only 1% of the time, historically)."),
    ("Risk Measurement", "Full Revaluation", "Repricing every position from scratch under a shocked scenario, using the same pricing functions as normal valuation - more accurate than a shortcut approximation."),
    ("Risk Measurement", "Expected Shortfall (ES)", "The average loss across all scenarios at or beyond the VaR threshold - 'given we're already in the bad tail, how bad on average?'"),
    ("Risk Measurement", "Parametric VaR", "VaR computed by assuming P&L is normally distributed, rather than sorting real historical scenarios."),
    ("Sensitivities", "Delta", "$ P&L per $1 move in the underlying. A stock's Delta equals its own quantity; an option's Delta comes from Black-Scholes."),
    ("Sensitivities", "Gamma", "How much Delta itself changes per $1 move in the underlying - the curvature only options have (a stock's Gamma is zero)."),
    ("Sensitivities", "Vega", "$ P&L per 1-volatility-point move in implied volatility. Only meaningful for options."),
    ("Sensitivities", "DV01", "Dollar Value of 1 basis point - the $ loss from a 1bp rise in the relevant yield, for a bond."),
    ("Sensitivities", "CS01", "The $ loss from a 1bp widening in credit spread, for a corporate bond. Equals DV01 for the same bond in this project's simplified model, since both bump one shared discount rate."),
    ("Sensitivities", "Basis Point (bp)", "0.0001, or 0.01% - the standard unit for yield and spread moves."),
    ("P&L & Stress", "Actual P&L", "The real, full-revaluation change in portfolio value between two dates."),
    ("P&L & Stress", "Explained P&L", "A reconstruction of Actual P&L using sensitivities x the real observed risk-factor changes - a first-order approximation."),
    ("P&L & Stress", "Residual", "Actual minus Explained - the part of the move sensitivities don't capture (mainly bond convexity here). Expected, not an error."),
    ("P&L & Stress", "Stress Testing", "Applying a deliberately chosen, often severe scenario to the portfolio, with no probability attached - unlike VaR's statistical approach."),
    ("Controls & Governance", "Limit", "A pre-approved maximum threshold for a risk metric."),
    ("Controls & Governance", "Utilization", "Actual metric value expressed as a % of its limit."),
    ("Controls & Governance", "GREEN / AMBER / RED", "Limit status: GREEN below the warning threshold, AMBER between warning and breach, RED at or above breach (100%+)."),
    ("Controls & Governance", "Control", "An automated data-quality or reconciliation check, with a PASS/WARN/FAIL outcome, a severity, and exception details."),
    ("Controls & Governance", "Reconciliation", "Comparing two independently-derived totals (e.g. a fresh recompute vs. a persisted value) to catch a break."),
    ("FRTB (Educational)", "GIRR", "General Interest Rate Risk - the FRTB risk class for rate/yield-curve sensitivity."),
    ("FRTB (Educational)", "Credit Spread Risk", "The FRTB risk class for corporate bond spread sensitivity."),
    ("FRTB (Educational)", "Curvature", "FRTB's regulatory version of Gamma - the nonlinear part of price risk Delta misses."),
]


def glossary_lookup(term):
    for _, t, d in GLOSSARY:
        if t == term:
            return d
    return ""


PAGES = ["Executive Dashboard", "Risk Explorer", "P&L & Stress",
         "Limits & Breach Investigation", "Data Quality / Controls", "FRTB Explorer",
         "How This Works"]
page = st.sidebar.radio("Page", PAGES)
st.sidebar.markdown("---")
st.sidebar.caption("All figures sourced live from the FastAPI layer, backed by the "
                    "PostgreSQL results of the most recent EOD pipeline run.")

try:
    requests.get(f"{API}/health", timeout=2)
except requests.exceptions.ConnectionError:
    st.error(f"Cannot reach the API at {API}. Start it with: `uvicorn src.api:app --port 8000`")
    st.stop()


# ============================================================================
# 1. EXECUTIVE DASHBOARD - audience: Senior Risk Manager
# Business question: "Is the book healthy right now, at a glance?"
# ============================================================================
if page == "Executive Dashboard":
    st.title("Executive Dashboard")
    st.caption("Senior Risk Manager view - as-of-date headline risk position")

    summary = get("/risk/summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Portfolio Value", f"${summary['portfolio_value']:,.0f}",
              help="Total mark-to-market value of all 40 positions, in USD - computed, not an input.")
    c2.metric("99% VaR (1-day)", f"${summary['var_99']:,.0f}", help=glossary_lookup("VaR (Value at Risk)"))
    c3.metric("99% Expected Shortfall", f"${summary['es_99']:,.0f}", help=glossary_lookup("Expected Shortfall (ES)"))
    c4.metric("Actual P&L (last move)", f"${summary['actual_pnl']:,.0f}", help=glossary_lookup("Actual P&L"))

    c5, c6, c7 = st.columns(3)
    c5.metric(f"Worst Stress Loss", f"${summary['worst_stress_pnl']:,.0f}",
              help=f"{summary['worst_stress_scenario']} — {glossary_lookup('Stress Testing')}")
    c6.metric("Max Limit Utilization", f"{summary['max_limit_utilization_pct']}%", help=glossary_lookup("Utilization"))
    c7.metric("Active Breaches (RED)", summary["active_breaches"],
               delta=None if summary["active_breaches"] == 0 else "needs attention", delta_color="inverse",
               help="Limits currently at RED status (utilization ≥ 100%). See the 'How This Works' page for what GREEN/AMBER/RED mean.")

    st.markdown("---")
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Rolling 99% VaR (60-day window)")
        st.caption("Computed from the 472 real historical scenarios (Module 4) using a rolling 60-day "
                   "trailing window - this project persists a single daily EOD snapshot (Module 1's "
                   "single-snapshot design), so this is the honest way to show a 'VaR history' trend "
                   "without fabricating multiple EOD runs.")
        hist = get("/risk/var/history")
        df = pd.DataFrame(hist)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["date"], y=df["var_99"], name="99% VaR", line=dict(color="#d62728")))
        fig.add_trace(go.Scatter(x=df["date"], y=df["var_95"], name="95% VaR", line=dict(color="#e6a817")))
        fig.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("Exposure by Asset Class")
        st.caption("Shown via Combined Severe stress P&L by asset class - a risk-weighted view, "
                   "not raw notional")
        stress = pd.DataFrame(get("/risk/stress", breakdown="asset_class"))
        combined = stress[stress["scenario_name"] == "Combined Severe Market Stress"]
        fig = go.Figure(go.Bar(x=combined["asset_class"], y=combined["stress_pnl"],
                                marker_color=["#d62728" if v < 0 else "#2ca02c" for v in combined["stress_pnl"]]))
        fig.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10),
                           yaxis_title="Combined stress scenario P&L ($)")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Limit Utilization")
    limits = pd.DataFrame(get("/risk/limits"))
    fig = go.Figure(go.Bar(
        x=limits["utilization_pct"], y=limits["metric"] + " (" + limits["scope_value"] + ")",
        orientation="h", marker_color=[status_color(s) for s in limits["status"]]))
    fig.add_vline(x=100, line_dash="dash", line_color="gray")
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Utilization %")
    st.plotly_chart(fig, use_container_width=True)


# ============================================================================
# 2. RISK EXPLORER - audience: Market Risk Analyst
# Business question: "Where exactly is our risk concentrated?"
# ============================================================================
elif page == "Risk Explorer":
    st.title("Risk Explorer")
    st.caption("Market Risk Analyst view - exposure and sensitivities by book/desk/asset class")

    with st.expander("What do Delta / Gamma / Vega / DV01 / CS01 mean?"):
        for term in ["Delta", "Gamma", "Vega", "DV01", "CS01"]:
            st.markdown(f"**{term}** — {glossary_lookup(term)}")
        st.caption("A blank cell means that metric doesn't apply to that position's asset class — e.g. "
                   "a stock has no DV01. It's not a missing value.")

    tab1, tab2, tab3 = st.tabs(["By Desk", "By Asset Class", "Position-Level"])

    with tab1:
        by_desk = pd.DataFrame(get("/risk/sensitivities", group_by="desk"))
        st.dataframe(by_desk.style.format({c: "{:,.1f}" for c in ["delta", "gamma", "vega", "dv01", "cs01"]}, na_rep="-"),
                     use_container_width=True)
        fig = go.Figure()
        for metric in ["dv01", "cs01"]:
            fig.add_trace(go.Bar(name=metric.upper(), x=by_desk["group_value"], y=by_desk[metric]))
        fig.update_layout(barmode="group", height=350, title="DV01 / CS01 by Desk")
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        by_ac = pd.DataFrame(get("/risk/sensitivities", group_by="asset_class"))
        st.dataframe(by_ac.style.format({c: "{:,.1f}" for c in ["delta", "gamma", "vega", "dv01", "cs01"]}, na_rep="-"),
                     use_container_width=True)

    with tab3:
        pos = pd.DataFrame(get("/risk/sensitivities"))
        desk_filter = st.multiselect("Filter by desk", pos["desk_name"].unique().tolist())
        if desk_filter:
            pos = pos[pos["desk_name"].isin(desk_filter)]
        st.dataframe(pos, use_container_width=True, height=400)


# ============================================================================
# 3. P&L & STRESS - audience: Market Risk Analyst / Senior Risk Manager
# Business question: "Why did we move, and how bad could it get?"
# ============================================================================
elif page == "P&L & Stress":
    st.title("P&L & Stress")
    st.caption("Why the portfolio moved, and what a hypothetical severe scenario would do to it")

    st.subheader("P&L Attribution Waterfall (most recent historical move)")
    with st.expander("What does this chart show?"):
        st.markdown(f"**Actual P&L** — {glossary_lookup('Actual P&L')}")
        st.markdown(f"**Explained P&L** — {glossary_lookup('Explained P&L')}")
        st.markdown(f"**Residual** — {glossary_lookup('Residual')}")
    pnl = get("/risk/pnl")
    st.caption(f"Attribution date: {pnl['scenario_date']} | Explained: "
               f"{100*pnl['explained_pnl']/pnl['actual_pnl']:.1f}% of actual move")
    components = ["equity_delta_pnl", "gamma_pnl", "vega_pnl", "rates_pnl", "credit_pnl", "fx_pnl", "residual_pnl"]
    labels = ["Equity/Delta", "Gamma", "Vega", "Rates/DV01", "Credit/CS01", "FX", "Residual"]
    values = [pnl[c] for c in components]
    fig = go.Figure(go.Waterfall(
        x=labels + ["Actual P&L"], measure=["relative"] * len(labels) + ["total"],
        y=values + [pnl["actual_pnl"]],
        decreasing=dict(marker_color="#d62728"), increasing=dict(marker_color="#2ca02c"),
        totals=dict(marker_color="#1f77b4"),
    ))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("Stress Scenario Comparison")
    stress_totals = pd.DataFrame(get("/risk/stress"))
    fig2 = go.Figure(go.Bar(x=stress_totals["scenario_name"], y=stress_totals["stress_pnl"],
                             marker_color="#d62728"))
    fig2.update_layout(height=350, yaxis_title="Total stress P&L ($)")
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Worst Scenario - Top Contributors")
    worst_scenario = stress_totals.iloc[stress_totals["stress_pnl"].idxmin()]["scenario_name"]
    by_desk = pd.DataFrame(get("/risk/stress", breakdown="desk"))
    worst = by_desk[by_desk["scenario_name"] == worst_scenario].sort_values("stress_pnl")
    st.caption(f"Scenario: {worst_scenario}")
    st.dataframe(worst[["desk_name", "stress_pnl"]], use_container_width=True)


# ============================================================================
# 4. LIMITS & BREACH INVESTIGATION - audience: Senior Risk Manager / BA-Controls
# Business question: "What's breached, and is it real?"
# ============================================================================
elif page == "Limits & Breach Investigation":
    st.title("Limits & Breach Investigation")
    st.caption("Current limit status, and a structured investigation for any active breach")
    st.caption("🟢 GREEN: below warning threshold  ·  🟡 AMBER: approaching the limit  ·  🔴 RED: breached (≥100% utilization)")

    limits = pd.DataFrame(get("/risk/limits"))
    for row in limits.itertuples():
        c1, c2 = st.columns([1, 5])
        c1.markdown(status_badge(row.status), unsafe_allow_html=True)
        c2.write(f"**{row.metric}** ({row.scope_type}: {row.scope_value}) - "
                 f"${row.actual_value:,.0f} / ${row.limit_value:,.0f} ({row.utilization_pct}%)")

    breaches = limits[limits["status"] == "RED"]
    if len(breaches):
        st.markdown("---")
        st.subheader("Breach Investigation")
        for row in breaches.itertuples():
            with st.expander(f"BREACH: {row.metric} - {row.scope_value}", expanded=True):
                controls = pd.DataFrame(get("/controls"))
                dq_pass = (controls["status"] == "PASS").all()
                st.write(f"**Data Quality:** {'PASS' if dq_pass else 'FAIL - see Data Quality page'}")
                st.write(f"**Utilization:** {row.utilization_pct}% (${row.actual_value:,.0f} vs "
                         f"${row.limit_value:,.0f} limit)")
                if row.scope_type == "Issuer":
                    frtb = pd.DataFrame(get("/risk/frtb"))
                    positions = pd.DataFrame(get("/positions"))
                    st.write("**Primary Contributors** (see Risk Explorer for full detail; "
                             "full investigation logic lives in `src/breach_investigation.py`)")
                st.info("Preliminary Assessment: run `python src/breach_investigation.py` for the full "
                        "structured workflow (data quality -> reconciliation -> prior/current exposure -> "
                        "contributors -> market drivers -> conclusion) built in Module 7c.")
    else:
        st.success("No active breaches.")


# ============================================================================
# 5. DATA QUALITY / CONTROLS - audience: Business Analyst / Controls
# Business question: "Can I trust today's numbers?"
# ============================================================================
elif page == "Data Quality / Controls":
    st.title("Data Quality / Controls")
    st.caption("Business Analyst / Controls view - every control run as part of the EOD pipeline")
    st.caption(f"A **control** is {glossary_lookup('Control').lower()} PASS is good; WARN/FAIL means "
               "something needs review before trusting today's other numbers.")

    controls = pd.DataFrame(get("/controls"))
    n_fail = (controls["status"] != "PASS").sum()
    st.metric("Controls Not Passing", n_fail, delta=None if n_fail == 0 else "review needed", delta_color="inverse")

    for row in controls.itertuples():
        c1, c2, c3 = st.columns([1, 1, 4])
        c1.markdown(status_badge(row.status), unsafe_allow_html=True)
        c2.write(row.severity)
        c3.write(row.control_name)
        if row.details and row.details not in ([], {}, None):
            with st.expander("details"):
                st.json(row.details)


# ============================================================================
# 6. FRTB EXPLORER - audience: Market Risk Analyst / Business Analyst
# Business question: "How would each position map onto FRTB risk classes?"
# EDUCATIONAL ONLY - no capital number is shown or implied anywhere on this page.
# ============================================================================
elif page == "FRTB Explorer":
    st.title("FRTB Explorer")
    st.warning("EDUCATIONAL MAPPING ONLY. No risk weights, correlations, DRC, RRAO, or capital "
               "calculation are implemented here. This page shows how positions map onto FRTB risk "
               "classes and which sensitivity applies - nothing on this page is a regulatory capital number.")

    frtb = pd.DataFrame(get("/risk/frtb"))
    risk_classes = ["All"] + sorted(frtb["frtb_risk_class"].unique().tolist())
    choice = st.selectbox("Filter by FRTB risk class", risk_classes)
    if choice != "All":
        frtb = frtb[frtb["frtb_risk_class"] == choice]

    st.dataframe(frtb, use_container_width=True, height=450)

    st.subheader("Row count by risk class")
    counts = pd.DataFrame(get("/risk/frtb")).groupby("frtb_risk_class").size().reset_index(name="rows")
    fig = go.Figure(go.Bar(x=counts["frtb_risk_class"], y=counts["rows"]))
    fig.update_layout(height=300, yaxis_title="Mapping rows (not capital)")
    st.plotly_chart(fig, use_container_width=True)


# ============================================================================
# 7. HOW THIS WORKS - audience: everyone
# Business question: "What do these entities and terms actually mean?"
# ============================================================================
elif page == "How This Works":
    st.title("How This Works")
    st.caption("The data model behind every page in this app, plus a searchable glossary of every term used.")

    st.subheader("How the data connects")
    st.caption("Followed through one real, concrete chain from this portfolio — the deliberately "
               "engineered JPMorgan Chase concentration that drives the RED breach on the Limits page.")

    chain = [
        ("DESK", "Fixed Income Desk", "An organisational unit covering related products."),
        ("BOOK", "Credit - Concentrated Book  (BK_CREDIT_CONC)", "A sub-ledger within the desk, grouped for risk aggregation."),
        ("POSITION", "POS0031  —  12,000,000 face value", "The net holding in one instrument within this book."),
        ("INSTRUMENT", "JPM-CB-2Y  —  JPMorgan Chase 2Y Corp Bond", "The security itself, defined by issuer, coupon, and maturity."),
        ("ISSUER", "JPMorgan Chase & Co", "The legal entity that issued this bond — also the issuer of a JPM stock and option position elsewhere in the book."),
    ]
    for i, (label, value, desc) in enumerate(chain):
        with st.container(border=True):
            c1, c2 = st.columns([1, 4])
            c1.markdown(f"**{label}**")
            c2.markdown(f"**{value}**  \n<span style='opacity:0.7'>{desc}</span>", unsafe_allow_html=True)
        if i < len(chain) - 1:
            st.markdown("<div style='text-align:center'>↓</div>", unsafe_allow_html=True)

    st.markdown("")
    with st.container(border=True):
        st.markdown("**RISK FACTOR** (a separate concept, linked to Instrument, not part of the chain above)")
        st.markdown("This bond's value depends on the risk factor `ISS_JPM-CS` (JPMorgan's credit spread) "
                    "and a matching Treasury yield — see the **Sensitivities** glossary entries below for "
                    "DV01/CS01, which measure exactly this dependency.")
    st.caption("An Equity Option's Instrument row also self-references another Instrument as its "
               "'underlying' — e.g. the JPM Call option points back to the JPM-EQ stock instrument.")

    st.markdown("---")
    st.subheader("Glossary")
    search = st.text_input("Search for a term", placeholder="e.g. DV01, VaR, breach, control...")
    categories = []
    for cat, _, _ in GLOSSARY:
        if cat not in categories:
            categories.append(cat)
    needle = search.strip().lower()
    any_match = False
    for cat in categories:
        items = [(t, d) for c, t, d in GLOSSARY if c == cat and
                 (needle in t.lower() or needle in d.lower())]
        if items:
            any_match = True
            with st.expander(f"{cat}  ({len(items)})", expanded=bool(needle)):
                for t, d in items:
                    st.markdown(f"**{t}** — {d}")
    if not any_match:
        st.info("No terms match that search.")
