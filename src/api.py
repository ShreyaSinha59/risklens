"""
Module 10a: FastAPI application layer

Thin JSON wrapper over the Postgres database built in Module 9 - every
endpoint is close to one of sql/queries.sql's queries. No calculation
happens here; this layer only reads what the EOD pipeline already
persisted. No authentication / enterprise infrastructure, per scope.

Run with: uvicorn api:app --reload --port 8000
"""

import math
import os
from typing import Optional

import pandas as pd
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query

# DATABASE_URL is set by the host (Render/Neon) in production; falls back to
# the local Postgres socket for local development.
DB_DSN = os.environ.get("DATABASE_URL", "host=/tmp port=5432 dbname=trading_book_risk")
app = FastAPI(title="Trading Book Risk API", version="1.0")


def query(sql, params=None):
    # psycopg2 only skips its own %-style parameter substitution when `vars`
    # is omitted entirely - passing even an empty list/dict still triggers it,
    # which breaks any literal '%' in the SQL (e.g. 'VaR 99%'). So: only pass
    # params through when there actually are some.
    conn = None
    try:
        conn = psycopg2.connect(DB_DSN)
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if params:
                    cur.execute(sql, params)
                else:
                    cur.execute(sql)
                return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        if conn is not None:
            conn.close()


def latest_as_of_date():
    rows = query("SELECT MAX(as_of_date) AS d FROM positions")
    if not rows or rows[0]["d"] is None:
        raise HTTPException(status_code=404, detail="No position data loaded yet")
    return rows[0]["d"]


# ---------------------------------------------------------------------------
# /positions - purpose: raw position blotter, optionally filtered.
# inputs: desk_id, book_id, asset_class (all optional query filters)
# output: list of positions with instrument/book/desk context
# source: positions JOIN books JOIN desks JOIN instruments
# ---------------------------------------------------------------------------
@app.get("/positions")
def get_positions(desk_id: Optional[str] = None, book_id: Optional[str] = None,
                   asset_class: Optional[str] = None):
    sql = """
        SELECT p.position_id, p.as_of_date, p.book_id, b.desk_id, d.desk_name,
               p.instrument_id, i.asset_class, p.quantity
        FROM positions p
        JOIN books b ON b.book_id = p.book_id
        JOIN desks d ON d.desk_id = b.desk_id
        JOIN instruments i ON i.instrument_id = p.instrument_id
        WHERE (%(desk_id)s IS NULL OR b.desk_id = %(desk_id)s)
          AND (%(book_id)s IS NULL OR p.book_id = %(book_id)s)
          AND (%(asset_class)s IS NULL OR i.asset_class = %(asset_class)s)
        ORDER BY p.position_id
    """
    return query(sql, {"desk_id": desk_id, "book_id": book_id, "asset_class": asset_class})


# ---------------------------------------------------------------------------
# /risk/summary - purpose: Executive Dashboard headline tiles.
# inputs: none
# output: portfolio value, 99% VaR/ES, actual P&L, worst stress loss, breach count
# source: position_valuations, risk_results, pnl_attribution, risk_limits JOIN risk_results
# ---------------------------------------------------------------------------
@app.get("/risk/summary")
def risk_summary():
    as_of = latest_as_of_date()
    portfolio_value = query("SELECT SUM(market_value_usd) AS v FROM position_valuations")[0]["v"]
    var99 = query("SELECT value FROM risk_results WHERE metric = 'Historical VaR 99%'")
    es99 = query("SELECT value FROM risk_results WHERE metric = 'Historical ES 99%'")
    pnl = query("SELECT actual_pnl FROM pnl_attribution ORDER BY as_of_date DESC LIMIT 1")
    worst_stress = query("""
        SELECT scenario_name, SUM(stress_pnl) AS total_pnl FROM stress_results
        GROUP BY scenario_name ORDER BY total_pnl ASC LIMIT 1
    """)
    breaches = query("""
        SELECT COUNT(*) AS n FROM risk_limits rl JOIN risk_results rr
          ON rr.scope_type = rl.scope_type AND rr.scope_value = rl.scope_value AND rr.metric = rl.metric
        WHERE rr.value / rl.limit_value >= 1.0
    """)
    max_utilization = query("""
        SELECT MAX(rr.value / rl.limit_value) AS u FROM risk_limits rl JOIN risk_results rr
          ON rr.scope_type = rl.scope_type AND rr.scope_value = rl.scope_value AND rr.metric = rl.metric
    """)
    return {
        "as_of_date": str(as_of),
        "portfolio_value": portfolio_value,
        "var_99": var99[0]["value"] if var99 else None,
        "es_99": es99[0]["value"] if es99 else None,
        "actual_pnl": pnl[0]["actual_pnl"] if pnl else None,
        "worst_stress_scenario": worst_stress[0]["scenario_name"] if worst_stress else None,
        "worst_stress_pnl": worst_stress[0]["total_pnl"] if worst_stress else None,
        "max_limit_utilization_pct": round(float(max_utilization[0]["u"]) * 100, 1) if max_utilization[0]["u"] else None,
        "active_breaches": breaches[0]["n"],
    }


# ---------------------------------------------------------------------------
# /risk/var - purpose: VaR/ES at all computed confidence levels.
# inputs: none
# output: list of {metric, value}
# source: risk_results (scope_type='Portfolio', metric LIKE VaR/ES)
# ---------------------------------------------------------------------------
@app.get("/risk/var")
def risk_var():
    sql = """
        SELECT metric, value FROM risk_results
        WHERE scope_type = 'Portfolio' AND (metric LIKE '%VaR%' OR metric LIKE '%ES%')
        ORDER BY metric
    """
    return query(sql)


# ---------------------------------------------------------------------------
# /risk/sensitivities - purpose: Delta/Gamma/Vega/DV01/CS01, optionally aggregated.
# inputs: group_by = one of 'desk','book','asset_class' (optional; omit for position-level)
# output: list of rows at the requested grain
# source: sensitivities JOIN positions/books/desks/instruments
# ---------------------------------------------------------------------------
@app.get("/risk/sensitivities")
def risk_sensitivities(group_by: Optional[str] = Query(None, pattern="^(desk|book|asset_class)$")):
    base_join = """
        FROM sensitivities s
        JOIN positions p ON p.position_id = s.position_id
        JOIN books b ON b.book_id = p.book_id
        JOIN desks d ON d.desk_id = b.desk_id
        JOIN instruments i ON i.instrument_id = p.instrument_id
    """
    if group_by is None:
        sql = f"SELECT s.position_id, p.instrument_id, d.desk_name, p.book_id, s.delta, s.gamma, s.vega, s.dv01, s.cs01 {base_join} ORDER BY s.position_id"
        return query(sql)
    group_col = {"desk": "d.desk_name", "book": "p.book_id", "asset_class": "i.asset_class"}[group_by]
    sql = f"""
        SELECT {group_col} AS group_value, SUM(s.delta) AS delta, SUM(s.gamma) AS gamma,
               SUM(s.vega) AS vega, SUM(s.dv01) AS dv01, SUM(s.cs01) AS cs01
        {base_join} GROUP BY {group_col} ORDER BY {group_col}
    """
    return query(sql)


# ---------------------------------------------------------------------------
# /risk/pnl - purpose: latest P&L attribution breakdown (Actual/Explained/Residual).
# inputs: none
# output: single object with the factor-level breakdown
# source: pnl_attribution (latest as_of_date)
# ---------------------------------------------------------------------------
@app.get("/risk/pnl")
def risk_pnl():
    rows = query("SELECT * FROM pnl_attribution ORDER BY as_of_date DESC LIMIT 1")
    if not rows:
        raise HTTPException(status_code=404, detail="No P&L attribution persisted yet")
    return rows[0]


# ---------------------------------------------------------------------------
# /risk/stress - purpose: stress scenario results.
# inputs: breakdown = 'asset_class' or 'desk' (optional; omit for scenario totals)
# output: list of {scenario_name, ...grain..., stress_pnl}
# source: stress_results, optionally joined to instruments/books/desks
# ---------------------------------------------------------------------------
@app.get("/risk/stress")
def risk_stress(breakdown: Optional[str] = Query(None, pattern="^(asset_class|desk)$")):
    if breakdown is None:
        return query("SELECT scenario_name, SUM(stress_pnl) AS stress_pnl FROM stress_results GROUP BY scenario_name ORDER BY stress_pnl ASC")
    if breakdown == "asset_class":
        sql = """
            SELECT sr.scenario_name, i.asset_class, SUM(sr.stress_pnl) AS stress_pnl
            FROM stress_results sr JOIN positions p ON p.position_id = sr.position_id
            JOIN instruments i ON i.instrument_id = p.instrument_id
            GROUP BY sr.scenario_name, i.asset_class ORDER BY sr.scenario_name, stress_pnl ASC
        """
    else:
        sql = """
            SELECT sr.scenario_name, d.desk_name, SUM(sr.stress_pnl) AS stress_pnl
            FROM stress_results sr JOIN positions p ON p.position_id = sr.position_id
            JOIN books b ON b.book_id = p.book_id JOIN desks d ON d.desk_id = b.desk_id
            GROUP BY sr.scenario_name, d.desk_name ORDER BY sr.scenario_name, stress_pnl ASC
        """
    return query(sql)


# ---------------------------------------------------------------------------
# /risk/limits - purpose: limit utilization and status (GREEN/AMBER/RED).
# inputs: breached_only (bool, default false)
# output: list of limits with actual/limit/utilization/status
# source: risk_limits JOIN risk_results (status computed at query time, never stored)
# ---------------------------------------------------------------------------
@app.get("/risk/limits")
def risk_limits(breached_only: bool = False):
    sql = """
        SELECT rl.limit_id, rl.metric, rl.scope_type, rl.scope_value, rl.limit_value,
               rr.value AS actual_value, ROUND(100 * rr.value / rl.limit_value, 1) AS utilization_pct,
               CASE WHEN rr.value / rl.limit_value >= 1.0 THEN 'RED'
                    WHEN rr.value / rl.limit_value >= rl.warning_pct THEN 'AMBER'
                    ELSE 'GREEN' END AS status
        FROM risk_limits rl
        JOIN risk_results rr ON rr.scope_type = rl.scope_type AND rr.scope_value = rl.scope_value AND rr.metric = rl.metric
        ORDER BY utilization_pct DESC
    """
    rows = query(sql)
    if breached_only:
        rows = [r for r in rows if r["status"] in ("RED", "AMBER")]
    return rows


# ---------------------------------------------------------------------------
# /controls - purpose: data quality / reconciliation control results.
# inputs: failed_only (bool, default false)
# output: list of controls with status/severity/details
# source: control_results
# ---------------------------------------------------------------------------
@app.get("/controls")
def controls(failed_only: bool = False):
    sql = "SELECT as_of_date, control_name, status, severity, details FROM control_results"
    if failed_only:
        sql += " WHERE status != 'PASS'"
    sql += " ORDER BY severity, control_name"
    return query(sql)


# ---------------------------------------------------------------------------
# /risk/frtb - purpose: educational FRTB risk-class mapping (Module 8).
# inputs: risk_class (optional filter)
# output: list of {position_id, instrument_id, frtb_risk_class, risk_factor, sensitivity_type, sensitivity_value}
# source: frtb_mapping - EDUCATIONAL ONLY, not a capital calculation
# ---------------------------------------------------------------------------
@app.get("/risk/frtb")
def risk_frtb(risk_class: Optional[str] = None):
    sql = """
        SELECT position_id, instrument_id, asset_class, frtb_risk_class, risk_factor,
               sensitivity_type, sensitivity_value
        FROM frtb_mapping
        WHERE %(risk_class)s IS NULL OR frtb_risk_class = %(risk_class)s
        ORDER BY position_id
    """
    return query(sql, {"risk_class": risk_class})


# ---------------------------------------------------------------------------
# /risk/var/history - purpose: a "VaR history" trend for the Executive
# Dashboard's chart. This project persists only a single EOD snapshot per
# run (Module 1's single-snapshot design), so there is no real multi-day
# risk_results series to chart. Rather than fabricate one, this computes a
# rolling 60-scenario 99%/95% VaR directly from the 472 REAL historical
# scenario P&Ls (Module 4) - genuine derived data, honestly labeled as a
# rolling-window view rather than actual persisted daily history.
# inputs: window (int, default 60)
# output: list of {date, var_95, var_99}
# source: data/processed/scenario_pnls.csv (not the DB - noted explicitly)
# ---------------------------------------------------------------------------
@app.get("/risk/var/history")
def risk_var_history(window: int = 60):
    try:
        pnl = pd.read_csv("data/processed/scenario_pnls.csv", index_col=0)["pnl"].sort_index()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="scenario_pnls.csv not found - run src/var_es.py first")
    if len(pnl) <= window:
        raise HTTPException(status_code=400, detail=f"Need more than {window} scenarios, have {len(pnl)}")

    rows = []
    for i in range(window, len(pnl)):
        w = pnl.iloc[i - window:i].sort_values()
        k95 = math.ceil(0.05 * window)
        k99 = math.ceil(0.01 * window)
        rows.append({"date": pnl.index[i], "var_95": -w.iloc[k95 - 1], "var_99": -w.iloc[k99 - 1]})
    return rows


@app.get("/health")
def health():
    return {"status": "ok"}
