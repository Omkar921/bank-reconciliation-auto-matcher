"""
Bank-to-GL matching engine.

The engine runs a transparent rule cascade. Each rule only looks at lines that
earlier (stricter) rules left open, and every match carries an audit trail:
which rule fired, the confidence score, and the components behind it.

    Rule 1  EXACT      amount equal AND reference/check no. equal AND date within
                       1 business day (checks: within the clearing window, since a
                       check clears days after it is written).        -> auto-cleared
    Rule 2  STRONG     amount equal AND date within +/-3 business days AND
                       payee similarity >= 90                         -> auto-cleared
    Rule 3  SUGGESTED  amount equal AND date within +/-5 business days AND
                       payee similarity >= 80                         -> BSA review queue
    Else    UNMATCHED  exception on the bank side or on the book side

Guard rails
-----------
* Strictly 1:1. Inside each rule, candidate pairs are ranked by confidence, then
  date proximity, then IDs (deterministic), and taken greedily; once a bank or GL
  line is used it can never match again.
* Bank-originated items (fees, interest, NSF, chargebacks) can only match a GL
  cash entry booked to a bank-charge / interest / returns account. They are never
  paired with a vendor payment just because the amount happens to agree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

HOLIDAYS = ["2026-10-12"]

# --- Tunable thresholds (kept in one place so a BSA can change policy) -------
EXACT_DATE_WINDOW = 1          # business days
CHECK_CLEARING_WINDOW = 15     # business days a check may take to be presented
STRONG_DATE_WINDOW = 3
STRONG_PAYEE_MIN = 90
SUGGESTED_DATE_WINDOW = 5
SUGGESTED_PAYEE_MIN = 80

BANK_ORIGINATED_TYPES = {"FEE", "INTEREST", "NSF", "CHARGEBACK"}
BANK_ORIGINATED_GL_ACCOUNTS = ("6150", "4900", "1250")  # bank charges, interest income, returned items

# Words that carry no identity in a payee string
_NOISE = {
    "INC", "LLC", "LLP", "CO", "CORP", "CORPORATION", "COMPANY", "LTD", "PTY", "THE",
    "ACH", "PPD", "CCD", "DEBIT", "CREDIT", "PMT", "PAYMENT", "POS", "DEPOSIT",
    "PAYPAL", "SQ", "COM", "WWW", "US", "USA", "INTL",
}


def normalize_payee(text: str) -> str:
    """Upper-case, drop punctuation, store/ref numbers and noise words."""
    if not isinstance(text, str):
        return ""
    s = re.sub(r"[^A-Z0-9 ]", " ", text.upper())
    tokens = [t for t in s.split() if t not in _NOISE and not any(ch.isdigit() for ch in t)]
    return " ".join(tokens)


def payee_score(bank_payee: str, gl_payee: str) -> float:
    """0-100 similarity between a bank payee string and a GL vendor/customer name.

    token_set_ratio handles word order and extra words ("ACME STEEL" vs
    "Acme Steel LLC"); partial_ratio handles truncation and run-together names
    ("ACMESTEEL" vs "Acme Steel"). We blend them (60/40) so neither alone dominates.
    """
    a, b = normalize_payee(bank_payee), normalize_payee(gl_payee)
    if not a or not b:
        return 0.0
    tset = fuzz.token_set_ratio(a, b)
    part = fuzz.partial_ratio(a.replace(" ", ""), b.replace(" ", ""))
    return round(0.6 * tset + 0.4 * part, 1)


def business_day_diff(d1: pd.Series, d2: pd.Series) -> np.ndarray:
    """Absolute business-day distance between two date columns."""
    a = pd.to_datetime(d1).values.astype("datetime64[D]")
    b = pd.to_datetime(d2).values.astype("datetime64[D]")
    return np.abs(np.busday_count(np.minimum(a, b), np.maximum(a, b), holidays=HOLIDAYS))


@dataclass
class MatchResult:
    matches: pd.DataFrame        # one row per bank<->GL pair (Exact / Strong / Suggested)
    unmatched_bank: pd.DataFrame
    unmatched_gl: pd.DataFrame
    bank: pd.DataFrame           # bank lines with match_status attached
    gl: pd.DataFrame             # GL lines with match_status attached
    kpis: dict


def _candidates(bank: pd.DataFrame, gl: pd.DataFrame) -> pd.DataFrame:
    """All bank x GL pairs with the same amount, scored on every component."""
    b = bank.assign(cents=(bank["amount"] * 100).round().astype("int64"))
    g = gl.assign(cents=(gl["amount"] * 100).round().astype("int64"))
    pairs = b.merge(g, on="cents", suffixes=("_bank", "_gl"))
    if pairs.empty:
        return pairs
    pairs["date_diff"] = business_day_diff(pairs["posted_date"], pairs["gl_date"])
    ref_b = pairs["reference_bank"].fillna("").astype(str).str.strip()
    ref_g = pairs["reference_gl"].fillna("").astype(str).str.strip()
    pairs["ref_match"] = (ref_b != "") & (ref_b == ref_g)
    bank_name = pairs["payee"].fillna("").where(pairs["payee"].fillna("") != "", pairs["description"])
    pairs["payee_score"] = [payee_score(x, y) for x, y in zip(bank_name, pairs["counterparty"])]

    # Guard rail: bank-originated items only pair with bank-charge style GL entries
    bank_orig = pairs["type"].isin(BANK_ORIGINATED_TYPES)
    gl_bankish = pairs["offset_account"].astype(str).str.startswith(BANK_ORIGINATED_GL_ACCOUNTS)
    pairs["category_ok"] = bank_orig == gl_bankish
    return pairs


def _assign_rule(p: pd.DataFrame) -> pd.Series:
    """Label each candidate pair with the strictest rule it satisfies (or None)."""
    exact_window = np.where(p["type"] == "CHECK", CHECK_CLEARING_WINDOW, EXACT_DATE_WINDOW)
    exact = p["ref_match"] & (p["date_diff"] <= exact_window)
    strong = (p["date_diff"] <= STRONG_DATE_WINDOW) & (p["payee_score"] >= STRONG_PAYEE_MIN)
    suggested = (p["date_diff"] <= SUGGESTED_DATE_WINDOW) & (p["payee_score"] >= SUGGESTED_PAYEE_MIN)
    # A bank-generated fee booked in GL by the same bank (payee "BANK") is an exact-date item
    bank_je = p["category_ok"] & p["type"].isin(BANK_ORIGINATED_TYPES) & (p["date_diff"] <= EXACT_DATE_WINDOW)
    rule = np.select([exact | bank_je, strong, suggested], ["Exact", "Strong", "Suggested"], default="")
    return pd.Series(np.where(p["category_ok"], rule, ""), index=p.index)


def _confidence(p: pd.DataFrame) -> pd.Series:
    """0-100 confidence: references dominate; otherwise payee 70% / date 30%."""
    date_component = (1 - p["date_diff"].clip(upper=SUGGESTED_DATE_WINDOW) / SUGGESTED_DATE_WINDOW) * 100
    conf = 0.7 * p["payee_score"] + 0.3 * date_component
    conf = np.where(p["rule"] == "Exact", 100.0, conf)
    return pd.Series(np.round(conf, 1), index=p.index)


def match(bank: pd.DataFrame, gl: pd.DataFrame) -> MatchResult:
    bank = bank.copy()
    gl = gl.copy()
    pairs = _candidates(bank, gl)
    taken_bank: set[str] = set()
    taken_gl: set[str] = set()
    chosen = []

    if not pairs.empty:
        pairs["rule"] = _assign_rule(pairs)
        pairs = pairs[pairs["rule"] != ""].copy()
        pairs["confidence"] = _confidence(pairs)
        # Cascade: finish every Exact pairing before any Strong, then Suggested
        for rule in ["Exact", "Strong", "Suggested"]:
            tier = pairs[pairs["rule"] == rule].sort_values(
                ["confidence", "date_diff", "statement_id", "gl_id"], ascending=[False, True, True, True])
            for row in tier.itertuples(index=False):
                if row.statement_id in taken_bank or row.gl_id in taken_gl:
                    continue  # 1:1 - each line can be used once
                taken_bank.add(row.statement_id)
                taken_gl.add(row.gl_id)
                chosen.append(row)

    cols = ["statement_id", "posted_date", "description", "payee", "reference_bank", "type", "amount_bank",
            "gl_id", "gl_date", "counterparty", "memo", "reference_gl", "journal_id", "source", "amount_gl",
            "rule", "confidence", "date_diff", "payee_score", "ref_match"]
    matches = pd.DataFrame(chosen, columns=pairs.columns)[cols] if chosen else pd.DataFrame(columns=cols)
    matches = matches.rename(
        columns={"reference_bank": "bank_reference", "reference_gl": "gl_reference",
                 "amount_bank": "amount", "amount_gl": "gl_amount", "rule": "match_status"})
    matches = matches.sort_values(["match_status", "posted_date", "statement_id"]).reset_index(drop=True)

    status_b = dict(zip(matches["statement_id"], matches["match_status"]))
    status_g = dict(zip(matches["gl_id"], matches["match_status"]))
    bank["match_status"] = bank["statement_id"].map(status_b).astype(object).fillna("Unmatched-Bank")
    gl["match_status"] = gl["gl_id"].map(status_g).astype(object).fillna("Unmatched-GL")
    bank["matched_gl_id"] = bank["statement_id"].map(dict(zip(matches["statement_id"], matches["gl_id"])))
    gl["matched_statement_id"] = gl["gl_id"].map(dict(zip(matches["gl_id"], matches["statement_id"])))

    unmatched_bank = classify_bank_exceptions(bank[bank["match_status"] == "Unmatched-Bank"].copy(), gl)
    unmatched_gl = classify_gl_exceptions(gl[gl["match_status"] == "Unmatched-GL"].copy(), gl, bank)
    unmatched_bank = flag_splits(unmatched_bank, unmatched_gl)
    kpis = compute_kpis(bank, gl, matches, unmatched_bank, unmatched_gl)
    return MatchResult(matches, unmatched_bank, unmatched_gl, bank, gl, kpis)


# --- Exception classification (reconciling items) -----------------------------
def classify_bank_exceptions(ub: pd.DataFrame, gl: pd.DataFrame) -> pd.DataFrame:
    """Explain why each bank line is open, in the language of a bank rec."""
    def cat(r):
        if r["type"] == "FEE":
            return "Bank fee"
        if r["type"] == "INTEREST":
            return "Interest income"
        if r["type"] == "NSF":
            return "NSF / returned item"
        if r["type"] == "CHARGEBACK":
            return "Chargeback"
        return "Unexplained bank item"
    ub["category"] = ub.apply(cat, axis=1) if len(ub) else pd.Series(dtype=str)
    ub["suggested_action"] = ub["category"].map({
        "Bank fee": "Book JE: Dr 6150 Bank Charges / Cr 1000 Cash",
        "Interest income": "Book JE: Dr 1000 Cash / Cr 4900 Interest Income",
        "NSF / returned item": "Reverse customer receipt; re-open AR and contact customer",
        "Chargeback": "Book JE to 1250 Returns/Disputes; open dispute with processor",
    }).fillna("Investigate: no GL counterpart within tolerance")
    # Near-miss: same counterparty, amount within $50 on the book side (e.g. short-paid wire)
    if len(ub):
        open_gl = gl[gl["match_status"] == "Unmatched-GL"]
        notes = []
        for r in ub.itertuples():
            note = ""
            if r.category == "Unexplained bank item":
                near = open_gl[(open_gl["amount"] - r.amount).abs().between(0.01, 50)]
                near = near[[payee_score(r.payee, c) >= 80 for c in near["counterparty"]]] if len(near) else near
                if len(near):
                    g = near.iloc[0]
                    note = f"Possible amount mismatch vs {g.gl_id} (diff ${g.amount - r.amount:,.2f})"
            notes.append(note)
        ub["exception_note"] = notes
        mism = ub["exception_note"].str.startswith("Possible amount mismatch")
        ub.loc[mism, "category"] = "Amount mismatch"
        ub.loc[mism, "suggested_action"] = "Book short-pay/wire fee difference or chase customer"
    else:
        ub["exception_note"] = ""
    return ub.reset_index(drop=True)


def classify_gl_exceptions(ug: pd.DataFrame, gl: pd.DataFrame, bank: pd.DataFrame) -> pd.DataFrame:
    matched_gl = gl[gl["match_status"] != "Unmatched-GL"]
    matched_keys = set(zip(matched_gl["amount"].round(2), matched_gl["counterparty"]))
    open_bank = bank[bank["match_status"] == "Unmatched-Bank"]
    cats, notes, actions = [], [], []
    for r in ug.itertuples():
        ref = str(r.reference) if isinstance(r.reference, str) or pd.notna(r.reference) else ""
        if (round(r.amount, 2), r.counterparty) in matched_keys:
            c, a = "Possible duplicate posting", "Confirm with AP; reverse the duplicate journal"
        elif r.amount < 0 and ref.isdigit():
            c, a = "Outstanding check", "Carry forward; follow up if not cleared in 90 days"
        elif r.amount > 0 and pd.Timestamp(r.gl_date) >= pd.Timestamp("2026-10-29"):
            c, a = "Deposit in transit", "Confirm bank credit in first days of next month"
        else:
            near = open_bank[(open_bank["amount"] - r.amount).abs().between(0.01, 50)]
            near = near[[payee_score(p, r.counterparty) >= 80 for p in near["payee"]]] if len(near) else near
            if len(near):
                c, a = "Amount mismatch", "Book short-pay/wire fee difference or chase customer"
            else:
                c, a = "Unexplained book item", "Investigate: no bank counterpart within tolerance"
        cats.append(c)
        actions.append(a)
        notes.append("")
    ug["category"] = cats
    ug["suggested_action"] = actions
    ug["exception_note"] = notes
    return ug.reset_index(drop=True)


def flag_splits(ub: pd.DataFrame, ug: pd.DataFrame) -> pd.DataFrame:
    """Hint (never auto-clear): a bank credit equal to the sum of two open GL lines
    for the same counterparty within 3 days is probably a combined payment."""
    if ub.empty or ug.empty:
        return ub
    for i, r in ub.iterrows():
        if r["category"] != "Unexplained bank item" or r["exception_note"]:
            continue
        cand = ug[(business_day_diff(pd.Series([r["posted_date"]] * len(ug)), ug["gl_date"]) <= 3)
                  & ug["counterparty"].map(lambda c: payee_score(r["payee"], c) >= 85).values]
        vals = cand[["gl_id", "amount"]].values
        cents = int(round(r["amount"] * 100))
        hit = next((f"{a[0]} + {b[0]}" for k, a in enumerate(vals) for b in vals[k + 1:]
                    if int(round((a[1] + b[1]) * 100)) == cents), None)
        if hit:
            ub.at[i, "category"] = "Possible split payment"
            ub.at[i, "exception_note"] = f"Equals {hit}"
            ub.at[i, "suggested_action"] = "Review as 1-to-many match; clear manually if confirmed"
            for gid in hit.split(" + "):
                j = ug.index[ug["gl_id"] == gid][0]
                ug.at[j, "category"] = "Possible split payment"
                ug.at[j, "exception_note"] = f"Part of {r['statement_id']} (${r['amount']:,.2f})"
                ug.at[j, "suggested_action"] = "Review as 1-to-many match; clear manually if confirmed"
    return ub


# --- KPIs ----------------------------------------------------------------------
def compute_kpis(bank, gl, matches, ub, ug) -> dict:
    """Headline numbers. Rates are fractions (0.95 = 95%); format at display time."""
    def status_count(s):
        return int((matches["match_status"] == s).sum())
    auto = matches[matches["match_status"].isin(["Exact", "Strong"])]
    bank_abs = bank["amount"].abs().sum()
    gl_abs = gl["amount"].abs().sum()
    def cat_sum(df, c):
        return round(float(df.loc[df["category"] == c, "amount"].sum()), 2)
    k = {
        "bank_lines": int(len(bank)),
        "gl_lines": int(len(gl)),
        "exact": status_count("Exact"),
        "strong": status_count("Strong"),
        "suggested": status_count("Suggested"),
        "auto_cleared": int(len(auto)),
        "unmatched_bank": int(len(ub)),
        "unmatched_gl": int(len(ug)),
        "unmatched_bank_abs": round(float(ub["amount"].abs().sum()), 2),
        "unmatched_gl_abs": round(float(ug["amount"].abs().sum()), 2),
        # Match rate: share of bank lines with any match (incl. Suggested pending review)
        "match_rate_count": len(matches) / len(bank) if len(bank) else 0.0,
        "match_rate_dollars": float(matches["amount"].abs().sum() / bank_abs) if bank_abs else 0.0,
        "auto_clear_rate_count": len(auto) / len(bank) if len(bank) else 0.0,
        "gl_match_rate_count": len(matches) / len(gl) if len(gl) else 0.0,
        "matched_abs": round(float(matches["amount"].abs().sum()), 2),
        "bank_abs": round(float(bank_abs), 2),
        "gl_abs": round(float(gl_abs), 2),
        "exception_count": int(len(ub) + len(ug)),
        "exception_abs": round(float(ub["amount"].abs().sum() + ug["amount"].abs().sum()), 2),
        "outstanding_checks": cat_sum(ug, "Outstanding check"),
        "outstanding_checks_n": int((ug["category"] == "Outstanding check").sum()),
        "deposits_in_transit": cat_sum(ug, "Deposit in transit"),
        "deposits_in_transit_n": int((ug["category"] == "Deposit in transit").sum()),
        "bank_charges": cat_sum(ub, "Bank fee"),
        "bank_charges_n": int((ub["category"] == "Bank fee").sum()),
        "interest_income": cat_sum(ub, "Interest income"),
        "nsf_items": cat_sum(ub, "NSF / returned item"),
        "chargebacks": cat_sum(ub, "Chargeback"),
        "bank_net": round(float(bank["amount"].sum()), 2),
        "gl_net": round(float(gl["amount"].sum()), 2),
    }
    return k


def load_inputs(data_dir="data"):
    bank = pd.read_csv(f"{data_dir}/bank_statement.csv", dtype={"reference": str},
                       parse_dates=["trans_date", "posted_date"])
    gl = pd.read_csv(f"{data_dir}/general_ledger.csv", dtype={"reference": str}, parse_dates=["gl_date"])
    return bank, gl
