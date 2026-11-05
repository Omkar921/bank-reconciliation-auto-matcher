"""
Streamlit exception-review workspace for the Bank Reconciliation Auto-Matcher.

    streamlit run app.py

Loads the precomputed outputs written by `python pipeline.py` so it opens fast.
If they are missing, it runs the matcher on data/*.csv on first load.
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
OUT = ROOT / "output"
STATUS_COLORS = {"Exact": "#1F3A5F", "Strong": "#2A9D8F", "Suggested": "#E9C46A",
                 "Unmatched-Bank": "#E76F51", "Unmatched-GL": "#6C757D"}

st.set_page_config(page_title="Bank Rec Auto-Matcher", page_icon="🏦", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 1rem;}
div[data-testid="stMetric"] {background:#F4F6F8; border:1px solid #E1E5EA; border-radius:10px; padding:12px 14px;}
div[data-testid="stMetricLabel"] p {font-size:0.85rem; color:#495057;}
h1 {color:#1F3A5F;}
</style>""", unsafe_allow_html=True)


@st.cache_data
def load():
    if not (OUT / "kpis.json").exists():
        import pipeline
        pipeline.main(["--no-generate"])
    k = json.loads((OUT / "kpis.json").read_text())
    m = pd.read_csv(OUT / "matches.csv", parse_dates=["posted_date", "gl_date"])
    ub = pd.read_csv(OUT / "unmatched_bank.csv", parse_dates=["posted_date"])
    ug = pd.read_csv(OUT / "unmatched_gl.csv", parse_dates=["gl_date"])
    ub["exception_note"] = ub["exception_note"].fillna("")
    ug["exception_note"] = ug["exception_note"].fillna("")
    return k, m, ub, ug


def money(x):
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


k, matches, ub, ug = load()

st.title("🏦 Bank Reconciliation Auto-Matcher")
st.caption("Month-end bank rec · Operating account ****4821 · October 2026 · "
           "Exact → Strong → Suggested rule cascade with a human review queue · synthetic data")

c = st.columns(6)
c[0].metric("Match rate (count)", f"{k['match_rate_count']:.1%}", f"{k['auto_clear_rate_count']:.1%} auto-cleared",
            delta_color="off", delta_arrow="off")
c[1].metric("Match rate ($)", f"{k['match_rate_dollars']:.1%}")
c[2].metric("Matched $", f"${k['matched_abs']/1e6:,.1f}M", f"{k['exact'] + k['strong'] + k['suggested']:,} pairs",
            delta_color="off", delta_arrow="off")
c[3].metric("Unmatched bank", f"{k['unmatched_bank']:,}", money(k["unmatched_bank_abs"]) + " abs", delta_color="off", delta_arrow="off")
c[4].metric("Unmatched GL", f"{k['unmatched_gl']:,}", money(k["unmatched_gl_abs"]) + " abs", delta_color="off", delta_arrow="off")
c[5].metric("Suggested to review", f"{k['suggested']:,}", "needs BSA sign-off", delta_color="off", delta_arrow="off")

tabs = st.tabs(["📊 Overview", "🟡 Suggested matches", "🔴 Unmatched bank", "⚪ Unmatched GL",
                "✅ Matched", "📥 Report"])

with tabs[0]:
    left, right = st.columns([1, 1.25])
    mix = pd.DataFrame({"status": list(STATUS_COLORS),
                        "lines": [k["exact"], k["strong"], k["suggested"], k["unmatched_bank"], k["unmatched_gl"]]})
    left.subheader("Match status mix")
    left.altair_chart(alt.Chart(mix).mark_arc(innerRadius=70).encode(
        theta="lines:Q",
        color=alt.Color("status:N", scale=alt.Scale(domain=list(STATUS_COLORS), range=list(STATUS_COLORS.values())),
                        legend=alt.Legend(orient="right", title=None)),
        tooltip=["status", alt.Tooltip("lines:Q", format=",")]).properties(height=300), use_container_width=True)

    exc = pd.concat([ub.assign(side="Bank"), ug.assign(side="GL")])
    exc["abs_amount"] = exc["amount"].abs()
    by_cat = exc.groupby(["category", "side"], as_index=False).agg(items=("amount", "size"), dollars=("abs_amount", "sum"))
    right.subheader("Exception $ by reconciling category")
    right.altair_chart(alt.Chart(by_cat).mark_bar().encode(
        x=alt.X("dollars:Q", title="Absolute $", axis=alt.Axis(format="$,.0s")),
        y=alt.Y("category:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
        color=alt.Color("side:N", scale=alt.Scale(domain=["Bank", "GL"], range=["#E76F51", "#6C757D"])),
        tooltip=["category", "side", "items", alt.Tooltip("dollars:Q", format="$,.2f")]).properties(height=300),
        use_container_width=True)

    a, b = st.columns([1.4, 1])
    daily = pd.concat([ub.assign(date=ub["posted_date"], side="Unmatched bank"),
                       ug.assign(date=ug["gl_date"], side="Unmatched GL")]).groupby(["date", "side"], as_index=False).size()
    a.subheader("Open exceptions by date")
    a.altair_chart(alt.Chart(daily).mark_bar().encode(
        x=alt.X("yearmonthdate(date):T", title=None), y=alt.Y("size:Q", title="Items"),
        color=alt.Color("side:N", scale=alt.Scale(domain=["Unmatched bank", "Unmatched GL"], range=["#E76F51", "#6C757D"]), legend=alt.Legend(orient="top", title=None)),
        tooltip=["date:T", "side", "size"]).properties(height=260), use_container_width=True)
    b.subheader("Reconciling items")
    rec = pd.DataFrame([
        ["Outstanding checks", k["outstanding_checks_n"], k["outstanding_checks"]],
        ["Deposits in transit", k["deposits_in_transit_n"], k["deposits_in_transit"]],
        ["Bank fees (unbooked)", k["bank_charges_n"], k["bank_charges"]],
        ["Interest income (unbooked)", 1, k["interest_income"]],
        ["NSF / returned items", int((ub["category"] == "NSF / returned item").sum()), k["nsf_items"]],
        ["Chargebacks", int((ub["category"] == "Chargeback").sum()), k["chargebacks"]],
    ], columns=["Item", "Count", "Amount"])
    b.dataframe(rec, hide_index=True, use_container_width=True,
                column_config={"Amount": st.column_config.NumberColumn(format="dollar")})
    b.caption(f"Auto-cleared precision vs. synthetic ground truth: **{k.get('auto_cleared_precision', 0):.1%}**")

with tabs[1]:
    sug = matches[matches["match_status"] == "Suggested"].sort_values("confidence", ascending=False)
    st.subheader(f"Review queue · {len(sug)} suggested matches")
    st.caption("Same amount, posted within 5 business days, payee similarity 80–90. "
               "Tick **Approve** to clear, leave unticked to send back to exceptions.")
    min_score = st.slider("Minimum payee score", 80, 90, 80)
    view = sug[sug["payee_score"] >= min_score][["statement_id", "posted_date", "payee", "amount", "gl_id", "gl_date",
                                                 "counterparty", "payee_score", "date_diff", "confidence"]]
    view.insert(0, "approve", False)
    edited = st.data_editor(view, hide_index=True, use_container_width=True, height=430, disabled=list(view.columns[1:]),
                            column_config={
                                "approve": st.column_config.CheckboxColumn("Approve"),
                                "amount": st.column_config.NumberColumn("Amount", format="dollar"),
                                "posted_date": st.column_config.DateColumn("Bank date"),
                                "gl_date": st.column_config.DateColumn("GL date"),
                                "payee": "Bank payee", "counterparty": "GL vendor / customer",
                                "payee_score": st.column_config.ProgressColumn("Payee score", min_value=0, max_value=100, format="%.1f"),
                                "date_diff": st.column_config.NumberColumn("Days apart"),
                                "confidence": st.column_config.NumberColumn("Confidence", format="%.1f")})
    n_ok = int(edited["approve"].sum())
    st.info(f"{n_ok} approved · {len(edited) - n_ok} pending · approved $ {edited.loc[edited['approve'], 'amount'].abs().sum():,.2f}")

money_cfg = {"amount": st.column_config.NumberColumn("Amount", format="dollar")}


def exception_tab(df, date_col, cols, title):
    cats = sorted(df["category"].unique())
    pick = st.multiselect("Category", cats, default=cats, key=title)
    d = df[df["category"].isin(pick)]
    m1, m2, m3 = st.columns(3)
    m1.metric("Items", f"{len(d):,}")
    m2.metric("Net $", money(d["amount"].sum()))
    m3.metric("Absolute $", money(d["amount"].abs().sum()))
    st.dataframe(d[cols].sort_values(date_col), hide_index=True, use_container_width=True, height=440,
                 column_config={**money_cfg, date_col: st.column_config.DateColumn(date_col.replace("_", " ").title())})


with tabs[2]:
    st.subheader("On the statement, not on the books")
    exception_tab(ub, "posted_date", ["statement_id", "posted_date", "amount", "description", "type", "category",
                                      "suggested_action", "exception_note"], "bank")
with tabs[3]:
    st.subheader("On the books, not on the statement")
    exception_tab(ug, "gl_date", ["gl_id", "gl_date", "amount", "counterparty", "memo", "source", "category",
                                  "suggested_action", "exception_note"], "gl")
with tabs[4]:
    st.subheader("Auto-cleared matches (audit trail)")
    rule = st.radio("Rule", ["Exact", "Strong"], horizontal=True)
    st.dataframe(matches[matches["match_status"] == rule][["statement_id", "posted_date", "payee", "amount", "gl_id",
                                                          "gl_date", "counterparty", "match_status", "confidence",
                                                          "date_diff", "payee_score", "ref_match"]],
                 hide_index=True, use_container_width=True, height=460, column_config=money_cfg)
with tabs[5]:
    st.subheader("Audit-ready Excel workbook")
    st.markdown("Six tabs for the controller's review binder: **Summary · Matched · Suggested Matches · "
                "Unmatched Bank · Unmatched GL · Reconciling Items** — with currency formats, frozen headers, "
                "filters and a reviewer sign-off column on the suggested queue.")
    xlsx = OUT / "reconciliation_report.xlsx"
    st.download_button("⬇️ Download reconciliation_report.xlsx", xlsx.read_bytes(), file_name=xlsx.name,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
