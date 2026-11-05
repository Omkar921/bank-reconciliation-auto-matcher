"""Unit tests for the matching engine using small, hand-built fixtures."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.matcher import match, payee_score  # noqa: E402


def bank_line(sid, date, amount, payee="", ref="", typ="ACH_DEBIT", desc=None):
    return dict(statement_id=sid, trans_date=pd.Timestamp(date), posted_date=pd.Timestamp(date), amount=amount,
                description=desc or f"{typ} {payee}", payee=payee, reference=ref, type=typ, bank_account="TEST")


def gl_line(gid, date, amount, counterparty, ref="", offset="2000-Accounts Payable", source="AP"):
    return dict(gl_id=gid, gl_date=pd.Timestamp(date), amount=amount, account=1000, offset_account=offset,
                cost_center="CC100", counterparty=counterparty, memo=f"Payment {counterparty}",
                journal_id=f"JE-{gid}", source=source, reference=ref)


def run(bank_rows, gl_rows):
    return match(pd.DataFrame(bank_rows), pd.DataFrame(gl_rows))


def test_exact_match_on_amount_and_check_number():
    r = run([bank_line("B1", "2026-10-14", -1250.00, ref="104311", typ="CHECK", desc="CHECK 104311")],
            [gl_line("G1", "2026-10-06", -1250.00, "Grainger Industrial Supply", ref="104311")])
    assert len(r.matches) == 1
    m = r.matches.iloc[0]
    assert (m.statement_id, m.gl_id, m.match_status) == ("B1", "G1", "Exact")
    assert m.confidence == 100.0 and bool(m.ref_match)


def test_check_number_mismatch_is_not_exact():
    r = run([bank_line("B1", "2026-10-14", -1250.00, ref="104311", typ="CHECK")],
            [gl_line("G1", "2026-10-14", -1250.00, "Grainger", ref="104999")])
    assert "Exact" not in set(r.matches["match_status"])


def test_fuzzy_payee_match_within_date_window():
    # Bank posts two business days later and prints a truncated, upper-case payee
    r = run([bank_line("B1", "2026-10-16", -8421.37, payee="OLD DOMINION FREIGHT L")],
            [gl_line("G1", "2026-10-14", -8421.37, "Old Dominion Freight Line")])
    m = r.matches.iloc[0]
    assert m.match_status == "Strong"
    assert m.date_diff == 2 and m.payee_score >= 90


def test_messy_processor_payee_goes_to_suggested_review():
    assert 80 <= payee_score("PAYPAL *BRIGHTLINEMANU", "Brightline Manufacturing") < 90
    r = run([bank_line("B1", "2026-10-20", 44210.93, payee="PAYPAL *BRIGHTLINEMANU", typ="DEPOSIT")],
            [gl_line("G1", "2026-10-20", 44210.93, "Brightline Manufacturing", offset="1200-Accounts Receivable")])
    assert r.matches.iloc[0].match_status == "Suggested"
    assert r.kpis["suggested"] == 1 and r.kpis["auto_cleared"] == 0


def test_outside_date_window_stays_unmatched():
    r = run([bank_line("B1", "2026-10-26", -500.00, payee="ACME STEEL")],
            [gl_line("G1", "2026-10-05", -500.00, "Acme Steel LLC")])
    assert r.matches.empty
    assert r.kpis["unmatched_bank"] == 1 and r.kpis["unmatched_gl"] == 1


def test_no_double_matching_same_line():
    # Two identical subscription debits on the bank, two on the GL, plus one extra GL copy
    bank = [bank_line("B1", "2026-10-02", -2480.00, payee="AMAZON WEB SERVICES"),
            bank_line("B2", "2026-10-09", -2480.00, payee="AMAZON WEB SERVICES")]
    gl = [gl_line("G1", "2026-10-02", -2480.00, "Amazon Web Services"),
          gl_line("G2", "2026-10-09", -2480.00, "Amazon Web Services"),
          gl_line("G3", "2026-10-09", -2480.00, "Amazon Web Services")]
    r = run(bank, gl)
    assert r.matches["statement_id"].is_unique and r.matches["gl_id"].is_unique
    assert len(r.matches) == 2
    # Closest dates win: B1<->G1, B2<->G2 (G3 left as a possible duplicate)
    pairs = set(zip(r.matches.statement_id, r.matches.gl_id))
    assert ("B1", "G1") in pairs
    assert r.unmatched_gl.iloc[0].category == "Possible duplicate posting"


def test_bank_fee_left_unmatched_without_gl_counterpart():
    # A $25 vendor payment exists in the GL but must NOT absorb the $25 bank fee
    r = run([bank_line("B1", "2026-10-07", -25.00, payee="BANK", typ="FEE", desc="INTL WIRE FEE")],
            [gl_line("G1", "2026-10-07", -25.00, "Bank of Parking LLC")])
    assert r.matches.empty
    ub = r.unmatched_bank.iloc[0]
    assert ub.category == "Bank fee" and "6150" in ub.suggested_action


def test_booked_bank_fee_does_match_bank_charge_entry():
    r = run([bank_line("B1", "2026-10-30", -1847.35, payee="BANK", typ="FEE")],
            [gl_line("G1", "2026-10-30", -1847.35, "Bank", offset="6150-Bank Charges", source="GL")])
    assert r.matches.iloc[0].match_status == "Exact"


def test_outstanding_check_left_as_unmatched_gl():
    r = run([bank_line("B1", "2026-10-15", -900.00, ref="104400", typ="CHECK")],
            [gl_line("G1", "2026-10-13", -900.00, "Cintas", ref="104400"),
             gl_line("G2", "2026-10-29", -3120.55, "Fastenal Company", ref="104455")])
    assert set(r.matches.gl_id) == {"G1"}
    ug = r.unmatched_gl.set_index("gl_id")
    assert ug.loc["G2", "category"] == "Outstanding check"
    assert r.kpis["outstanding_checks"] == pytest.approx(-3120.55)


def test_kpi_match_rate_sanity():
    bank = [bank_line("B1", "2026-10-05", -100.00, ref="R1"),
            bank_line("B2", "2026-10-06", -300.00, ref="R2"),
            bank_line("B3", "2026-10-07", -600.00, payee="BANK", typ="FEE")]
    gl = [gl_line("G1", "2026-10-05", -100.00, "A", ref="R1"), gl_line("G2", "2026-10-06", -300.00, "B", ref="R2")]
    k = run(bank, gl).kpis
    assert k["match_rate_count"] == pytest.approx(2 / 3)
    assert k["match_rate_dollars"] == pytest.approx(400 / 1000)
    assert 0 <= k["match_rate_count"] <= 1  # stored as a fraction, never 66.7 or 6,667%
    assert k["exception_count"] == 1 and k["exception_abs"] == pytest.approx(600)
    assert k["exact"] + k["strong"] + k["suggested"] + k["unmatched_bank"] == k["bank_lines"]


def test_full_sample_pipeline_is_reproducible_and_accurate(tmp_path):
    from src.generate_data import generate
    bank, gl, truth = generate(tmp_path, seed=42)
    r = match(pd.read_csv(tmp_path / "bank_statement.csv", dtype={"reference": str}),
              pd.read_csv(tmp_path / "general_ledger.csv", dtype={"reference": str}))
    t = truth.dropna(subset=["statement_id", "gl_id"])
    expected = set(zip(t.statement_id, t.gl_id))
    auto = r.matches[r.matches.match_status.isin(["Exact", "Strong"])]
    precision = sum(p in expected for p in zip(auto.statement_id, auto.gl_id)) / len(auto)
    assert precision >= 0.99
    assert 2000 <= r.kpis["bank_lines"] <= 4000
