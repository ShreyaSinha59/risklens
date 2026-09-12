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


PAGES = ["Executive Dashboard", "Risk Explorer", "P&L & Stress",
         "Limits & Breach Investigation", "Data Quality / Controls", "FRTB Explorer"]
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
    c1.metric("Portfolio Value", f"${summary['portfolio_value']:,.0f}")
    c2.metric("99% VaR (1-day)", f"${summary['var_99']:,.0f}")
    c3.metric("99% Expected Shortfall", f"${summary['es_99']:,.0f}")
    c4.metric("Actual P&L (last move)", f"${summary['actual_pnl']:,.0f}")

    c5, c6, c7 = st.columns(3)
    c5.metric(f"Worst Stress Loss", f"${summary['worst_stress_pnl']:,.0f}", help=summary['worst_stress_scenario'])
    c6.metric("Max Limit Utilization", f"{summary['max_limit_utilization_pct']}%")
    c7.metric("Active Breaches (RED)", summary["active_breaches"],
               delta=None if summary["active_breaches"] == 0 else "needs attention", delta_color="inverse")

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
