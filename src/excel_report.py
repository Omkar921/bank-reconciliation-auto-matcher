"""Audit-ready Excel reconciliation workbook (openpyxl)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY = "1F3A5F"
TEAL = "2A9D8F"
AMBER = "E9C46A"
RED = "E76F51"
GREY = "F4F6F8"
CURRENCY = '"$"#,##0.00;[Red]-"$"#,##0.00'
PCT = "0.0%"
THIN = Side(style="thin", color="D0D7DE")
HEADER_FILL = PatternFill("solid", fgColor=NAVY)
HEADER_FONT = Font(bold=True, color="FFFFFF")


def _write_table(ws, df: pd.DataFrame, start_row: int = 4, money_cols=(), pct_cols=(), tab=NAVY, title="", subtitle=""):
    ws.sheet_properties.tabColor = tab
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws["A2"] = subtitle
    ws["A2"].font = Font(italic=True, color="555555")
    for j, col in enumerate(df.columns, 1):
        c = ws.cell(row=start_row, column=j, value=col.replace("_", " ").title())
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = Border(bottom=THIN)
    for i, row in enumerate(df.itertuples(index=False), start_row + 1):
        for j, v in enumerate(row, 1):
            if isinstance(v, pd.Timestamp):
                v = v.date()
            elif pd.isna(v) if not isinstance(v, (list, dict)) else False:
                v = None
            c = ws.cell(row=i, column=j, value=v)
            if (i - start_row) % 2 == 0:
                c.fill = PatternFill("solid", fgColor=GREY)
    for j, col in enumerate(df.columns, 1):
        letter = get_column_letter(j)
        fmt = CURRENCY if col in money_cols else PCT if col in pct_cols else ("yyyy-mm-dd" if "date" in col and "diff" not in col else None)
        if fmt:
            for cell in ws[letter][start_row:]:
                cell.number_format = fmt
        width = max([len(str(col))] + [len(str(x)) for x in df[col].head(300)]) + 2
        ws.column_dimensions[letter].width = min(max(width, 10), 48)
    ws.row_dimensions[start_row].height = 30
    ws.freeze_panes = ws.cell(row=start_row + 1, column=3)
    if len(df):
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(df.columns))}{start_row + len(df)}"


def _kpi(ws, row, label, value, fmt=None, bold=False):
    ws.cell(row=row, column=2, value=label).font = Font(bold=bold)
    c = ws.cell(row=row, column=3, value=value)
    c.font = Font(bold=True, color=NAVY)
    if fmt:
        c.number_format = fmt
    c.alignment = Alignment(horizontal="right")


def _section(ws, row, text):
    c = ws.cell(row=row, column=2, value=text)
    c.font = Font(bold=True, color="FFFFFF")
    for col in (2, 3, 4):
        ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor=TEAL)


def write_report(result, path: str | Path = "output/reconciliation_report.xlsx", period="October 2026"):
    k = result.kpis
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.sheet_properties.tabColor = NAVY
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["C"].width = 20
    ws.column_dimensions["D"].width = 60
    ws["B1"] = "Bank Reconciliation - Auto-Match Summary"
    ws["B1"].font = Font(bold=True, size=16, color=NAVY)
    ws["B2"] = f"Operating account ****4821 · Period: {period} · Synthetic sample data"
    ws["B2"].font = Font(italic=True, color="555555")

    r = 4
    _section(ws, r, "Volume & match rate"); r += 1
    for label, val, fmt in [
        ("Bank statement lines", k["bank_lines"], "#,##0"), ("GL cash (1000) lines", k["gl_lines"], "#,##0"),
        ("Match rate - bank lines (count)", k["match_rate_count"], PCT),
        ("Match rate - bank lines ($)", k["match_rate_dollars"], PCT),
        ("Auto-cleared rate (Exact + Strong)", k["auto_clear_rate_count"], PCT),
        ("Matched $ (absolute)", k["matched_abs"], CURRENCY),
        ("Unmatched bank $ (absolute)", k["unmatched_bank_abs"], CURRENCY),
        ("Unmatched GL $ (absolute)", k["unmatched_gl_abs"], CURRENCY)]:
        _kpi(ws, r, label, val, fmt); r += 1
    r += 1
    _section(ws, r, "Rule breakdown"); r += 1
    rule_start = r
    for label, val in [("Exact (auto-cleared)", k["exact"]), ("Strong (auto-cleared)", k["strong"]),
                       ("Suggested (BSA review)", k["suggested"]), ("Unmatched - bank", k["unmatched_bank"]),
                       ("Unmatched - GL", k["unmatched_gl"])]:
        _kpi(ws, r, label, val, "#,##0"); r += 1
    rule_end = r - 1
    r += 1
    _section(ws, r, "Reconciling items"); r += 1
    for label, val, n in [
        ("Outstanding checks", k["outstanding_checks"], k["outstanding_checks_n"]),
        ("Deposits in transit", k["deposits_in_transit"], k["deposits_in_transit_n"]),
        ("Bank fees not yet booked", k["bank_charges"], k["bank_charges_n"]),
        ("Interest income not yet booked", k["interest_income"], 1),
        ("NSF / returned items", k["nsf_items"], None), ("Chargebacks", k["chargebacks"], None)]:
        _kpi(ws, r, label, val, CURRENCY)
        if n:
            ws.cell(row=r, column=4, value=f"{n} item(s)")
        r += 1
    r += 1
    _section(ws, r, "Balance proof (activity only)"); r += 1
    ub, ug = result.unmatched_bank, result.unmatched_gl
    adj_bank = k["bank_net"] + ug["amount"].sum()      # book-only items explain bank -> book
    adj_book = k["gl_net"] + ub["amount"].sum()        # bank-only items explain book -> bank
    for label, val in [("Net bank activity", k["bank_net"]), ("Net book activity", k["gl_net"]),
                       ("Bank activity + open GL items", adj_bank), ("Book activity + open bank items", adj_book),
                       ("Difference (should be $0.00)", round(adj_bank - adj_book, 2))]:
        _kpi(ws, r, label, round(val, 2), CURRENCY); r += 1
    r += 1
    _section(ws, r, "Narrative"); r += 1
    narrative = [
        f"{k['match_rate_count']:.1%} of {k['bank_lines']:,} bank lines matched to the GL; "
        f"{k['auto_clear_rate_count']:.1%} cleared automatically by Exact/Strong rules.",
        f"{k['suggested']} suggested matches need reviewer sign-off before clearing (see 'Suggested Matches').",
        f"{k['outstanding_checks_n']} outstanding checks (${-k['outstanding_checks']:,.2f}) and "
        f"{k['deposits_in_transit_n']} deposits in transit (${k['deposits_in_transit']:,.2f}) are normal timing items.",
        f"Bank fees (${-k['bank_charges']:,.2f}), interest (${k['interest_income']:,.2f}), NSF returns and chargebacks "
        "need adjusting journal entries in the GL.",
        "Possible duplicates, split payments and amount mismatches are flagged for investigation, never auto-cleared.",
    ]
    for line in narrative:
        c = ws.cell(row=r, column=2, value="• " + line)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 32
        r += 1

    pie = PieChart()
    pie.title = "Match status mix"
    pie.add_data(Reference(ws, min_col=3, min_row=rule_start, max_row=rule_end))
    pie.set_categories(Reference(ws, min_col=2, min_row=rule_start, max_row=rule_end))
    pie.height, pie.width = 8, 12
    ws.add_chart(pie, "F4")

    m = result.matches.copy()
    _write_table(wb.create_sheet("Matched"), m[m["match_status"] != "Suggested"],
                 money_cols={"amount", "gl_amount"}, tab=TEAL, title="Matched items (auto-cleared)",
                 subtitle="Bank (left) and GL (right) side by side with the rule, confidence and score components")
    sug = m[m["match_status"] == "Suggested"].sort_values("confidence", ascending=False).assign(
        reviewer_decision="", reviewer_initials="")
    _write_table(wb.create_sheet("Suggested Matches"), sug, money_cols={"amount", "gl_amount"}, tab=AMBER,
                 title="Suggested matches - BSA review queue",
                 subtitle="Same amount, date within 5 business days, payee similarity 80-90. Approve or reject each line.")
    bank_cols = ["statement_id", "posted_date", "amount", "description", "payee", "reference", "type",
                 "category", "suggested_action", "exception_note"]
    _write_table(wb.create_sheet("Unmatched Bank"), ub[bank_cols], money_cols={"amount"}, tab=RED,
                 title="Unmatched bank items", subtitle="On the statement, not on the books")
    gl_cols = ["gl_id", "gl_date", "amount", "counterparty", "memo", "offset_account", "journal_id", "source",
               "reference", "category", "suggested_action", "exception_note"]
    _write_table(wb.create_sheet("Unmatched GL"), ug[gl_cols], money_cols={"amount"}, tab=RED,
                 title="Unmatched GL items", subtitle="On the books, not on the statement")

    rec = pd.concat([
        ub.assign(side="Bank", item_id=ub["statement_id"], date=ub["posted_date"], detail=ub["description"]),
        ug.assign(side="GL", item_id=ug["gl_id"], date=ug["gl_date"], detail=ug["memo"]),
    ])[["category", "side", "item_id", "date", "amount", "detail", "suggested_action"]]
    summary = rec.groupby(["category", "side"], as_index=False).agg(items=("item_id", "count"), amount=("amount", "sum"))
    summary = summary.sort_values("amount", key=abs, ascending=False)
    ws6 = wb.create_sheet("Reconciling Items")
    _write_table(ws6, summary, money_cols={"amount"}, tab="6C757D", title="Reconciling items by category",
                 subtitle="Summary first, detail below")
    start = len(summary) + 7
    ws6.cell(row=start - 1, column=1, value="Detail").font = Font(bold=True, size=12, color=NAVY)
    for j, col in enumerate(rec.columns, 1):
        c = ws6.cell(row=start, column=j, value=col.replace("_", " ").title())
        c.fill, c.font = HEADER_FILL, HEADER_FONT
    for i, row in enumerate(rec.sort_values(["category", "date"]).itertuples(index=False), start + 1):
        for j, v in enumerate(row, 1):
            c = ws6.cell(row=i, column=j, value=v.date() if isinstance(v, pd.Timestamp) else v)
            if j == 5:
                c.number_format = CURRENCY
            if j == 4:
                c.number_format = "yyyy-mm-dd"
    ws6.column_dimensions["F"].width = 44
    ws6.column_dimensions["G"].width = 52

    bar = BarChart()
    bar.type = "bar"
    bar.title = "Exception items by category"
    bar.add_data(Reference(ws6, min_col=3, min_row=4, max_row=4 + len(summary)), titles_from_data=True)
    bar.set_categories(Reference(ws6, min_col=1, min_row=5, max_row=4 + len(summary)))
    bar.height, bar.width = 9, 16
    ws6.add_chart(bar, "I4")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
