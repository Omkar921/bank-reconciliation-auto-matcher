"""
Synthetic data generator for the Bank Reconciliation Auto-Matcher.

Creates one month (October 2026) of activity for a fictional mid-size
manufacturer, "Northwind Fabrication Co.", on a single operating account:

* data/bank_statement.csv  - lines as they appear on the bank statement
* data/general_ledger.csv  - cash-account (1000) entries from the books
* data/ground_truth.csv    - the *intended* bank<->GL pairing for every line,
                             used only to score the matcher (never by it)

Every scenario a month-end reconciler sees is baked in:
exact matches, timing differences, messy processor payee strings, bank-only
items (fees, interest, NSF, chargebacks), book-only items (outstanding checks,
deposits in transit), short-paid wires, split deposits and duplicate postings.

All data is synthetic. The generator is seeded, so results are reproducible.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
MONTH_START = pd.Timestamp("2026-10-01")
MONTH_END = pd.Timestamp("2026-10-31")
BANK_ACCOUNT = "OPERATING-****4821"
CASH_ACCOUNT = 1000

# Business days in October 2026 (US federal holiday Oct 12 is a bank holiday)
HOLIDAYS = ["2026-10-12"]
BDAYS = pd.bdate_range(MONTH_START, MONTH_END, freq="C", holidays=HOLIDAYS)

VENDORS = [
    "Grainger Industrial Supply", "Fastenal Company", "McMaster-Carr Supply", "Uline Inc",
    "Amazon Web Services", "Microsoft Corporation", "Salesforce Inc", "Adobe Inc",
    "Zoom Video Communications", "Slack Technologies", "Atlassian Pty Ltd", "DocuSign Inc",
    "FedEx Freight", "UPS Supply Chain", "Old Dominion Freight Line", "XPO Logistics",
    "Comcast Business", "Verizon Wireless", "AT&T Business", "Duke Energy",
    "Piedmont Natural Gas", "Waste Management Inc", "Cintas Corporation", "Aramark Uniform",
    "Staples Business Advantage", "Office Depot", "Iron Mountain", "ADT Commercial",
    "Hartford Insurance", "Travelers Casualty", "BlueCross BlueShield", "MetLife Group Benefits",
    "Acme Steel LLC", "Carolina Metal Works", "Summit Packaging LLC", "Blue Ridge Plastics",
    "Precision Tooling Inc", "Apex Hydraulics", "Keystone Bearings Co", "Liberty Fasteners",
    "Delta Electrical Contractors", "Triad Mechanical Services", "Pioneer Chemical Supply",
    "Harbor Freight Tools", "Sherwin-Williams", "Lowe's Pro Supply", "Home Depot Pro",
    "Ryder Truck Rental", "Penske Logistics", "Enterprise Fleet Mgmt", "Sysco Foodservice",
    "Robert Half Staffing", "Kforce Inc", "Deloitte Tax LLP", "Smith & Patel CPAs",
    "Baker Donelson Law", "Gartner Inc", "LinkedIn Corporation", "Indeed Inc",
    "Paychex Benefits", "Concur Technologies", "Oracle America Inc", "SAP America",
    "Dell Technologies", "CDW Direct", "Insight Enterprises", "Hewlett Packard Enterprise",
    "Granite Ridge Properties", "Crescent Industrial REIT", "Shred-It USA",
    "Rockwell Automation", "Siemens Industry Inc", "Parker Hannifin", "Emerson Electric",
    "Honeywell Intl", "3M Company", "Eaton Corporation", "ABB Inc", "Mouser Electronics",
    "Digi-Key Electronics", "Allied Electronics", "Newark Element14", "Arrow Electronics",
]
CUSTOMERS = [
    "Brightline Manufacturing", "Coastal Marine Systems", "Evergreen Building Products",
    "Frontier Agri Equipment", "Granite State Machinery", "Highland Auto Parts",
    "Ironwood Construction", "Juniper Medical Devices", "Kestrel Aerospace",
    "Lakeshore HVAC", "Meridian Energy Partners", "Northstar Robotics", "Oakridge Furniture",
    "Pacific Rim Distributors", "Quarry Hill Contractors", "Redwood Solar LLC",
    "Silverline Rail Services", "Tidewater Shipbuilding", "Union Pacific Components",
    "Vanguard Defense Systems", "Westfield Packaging", "Yellowstone Mining Supply",
    "Zenith Elevator Co", "Atlas Industrial Group", "Beacon Water Technologies",
    "Cedar Point Fabricators", "Dominion Pump & Valve", "Eastgate Logistics",
    "Falcon Trailer Works", "Greenfield Ag Co-op", "Harbor Point Marine", "Ironclad Security",
    "Jetstream Air Systems", "Keystone Rail Car", "Lone Star Drilling", "Mesa Verde Mining",
    "Nova Scotia Lumber", "Orion Aerospace Parts", "Prairie Wind Energy", "Riverbend Foods",
]
# Processor-style aliases a bank actually prints for some payees
ALIASES = {
    "Amazon Web Services": ["AMAZON.COM*2K8R3", "AMZN MKTP US*7Y1Q", "AWS AMAZON WEB SVCS"],
    "Acme Steel LLC": ["PAYPAL *ACME STEEL", "PAYPAL *ACMESTEEL LLC"],
    "Microsoft Corporation": ["MSFT *AZURE 0042", "MICROSOFT*365 E5"],
    "Adobe Inc": ["ADOBE *ACROPRO SUBS", "ADOBE  *CREATIVE CLD"],
    "Zoom Video Communications": ["ZOOM.US 888-799-9666", "ZOOM VIDEO COMM"],
    "Salesforce Inc": ["SALESFORCE.COM INC", "SFDC*SALESFORCE"],
    "Harbor Freight Tools": ["SQ *HARBOR FREIGHT", "HARBOR FRT TOOLS 0231"],
    "Home Depot Pro": ["THE HOME DEPOT #4471", "HOMEDEPOT.COM PRO"],
    "Lowe's Pro Supply": ["LOWES #01962*", "LOWE'S PRO SUPPLY"],
    "Summit Packaging LLC": ["SQ *SUMMIT PKG", "SUMMIT PACKAGING L"],
}


@dataclass
class Book:
    bank: list = field(default_factory=list)
    gl: list = field(default_factory=list)
    truth: list = field(default_factory=list)


def _ref(prefix: str, rng: random.Random, n: int = 8) -> str:
    return prefix + "".join(rng.choices(string.digits, k=n))


def _bday_offset(d: pd.Timestamp, n: int) -> pd.Timestamp:
    """Shift a date by n business days (respecting the bank holiday)."""
    return pd.Timestamp(np.busday_offset(d.date(), n, roll="forward", holidays=HOLIDAYS))


def bank_clean_name(name: str) -> str:
    """How a bank prints a clean ACH payee: upper case, punctuation stripped, 22 chars."""
    s = name.upper().replace(",", "").replace(".", "").replace("'", "")
    for suf in (" INC", " LLC", " CORPORATION", " COMPANY", " CO", " LLP"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s[:22].strip()


def bank_messy_name(name: str, rng: random.Random) -> str:
    """A messy processor-style payee string (PayPal/Square prefixes, store ids, truncation)."""
    if name in ALIASES:
        return rng.choice(ALIASES[name])
    base = bank_clean_name(name)
    words = base.split()
    style = rng.randint(0, 3)
    if style == 0:
        return f"PAYPAL *{''.join(words[:2])[:14]}"
    if style == 1:
        return f"SQ *{' '.join(words[:2])[:16]}"
    if style == 2:
        return f"{' '.join(words)[:16]} #{rng.randint(100, 9999)}"
    return f"{words[0][:10]}*{_ref('', rng, 5)} {' '.join(words[1:])[:8]}".strip()


class Generator:
    def __init__(self, seed: int = SEED):
        self.rng = random.Random(seed)
        self.np = np.random.default_rng(seed)
        self.b = Book()
        self._sid = 0
        self._gid = 0
        self._jid = 50000
        self._chk = 104200

    # ---- primitives -------------------------------------------------------
    def bank(self, trans_date, posted_date, amount, description, payee, ref, typ):
        self._sid += 1
        sid = f"BS-{self._sid:05d}"
        self.b.bank.append(dict(statement_id=sid, trans_date=trans_date.date(), posted_date=posted_date.date(),
                                amount=round(amount, 2), description=description, payee=payee,
                                reference=ref, type=typ, bank_account=BANK_ACCOUNT))
        return sid

    def gl(self, gl_date, amount, offset_account, cost_center, counterparty, memo, source, ref=""):
        self._gid += 1
        self._jid += 1
        gid = f"GL-{self._gid:05d}"
        self.b.gl.append(dict(gl_id=gid, gl_date=gl_date.date(), amount=round(amount, 2), account=CASH_ACCOUNT,
                              offset_account=offset_account, cost_center=cost_center,
                              counterparty=counterparty, memo=memo, journal_id=f"JE-{self._jid}",
                              source=source, reference=ref))
        return gid

    def truth(self, scenario, sid="", gid=""):
        self.b.truth.append(dict(scenario=scenario, statement_id=sid, gl_id=gid))

    def day(self, lo=0, hi=None):
        days = BDAYS[lo:hi]
        return days[self.rng.randrange(len(days))]

    def amt(self, lo, hi):
        """Log-uniform dollar amount with cents (vendor/customer spend is skewed)."""
        return round(float(np.exp(self.np.uniform(np.log(lo), np.log(hi)))), 2)

    def cc(self):
        return self.rng.choice(["CC100-Admin", "CC200-Ops", "CC300-Plant", "CC400-Sales", "CC500-IT"])

    # ---- scenarios --------------------------------------------------------
    def ap_checks(self, cleared=380, outstanding=62):
        for i in range(cleared + outstanding):
            self._chk += 1
            v = self.rng.choice(VENDORS)
            a = -self.amt(150, 40000)
            if i < cleared:
                d = self.day(0, -3)
                gid = self.gl(d, a, "2000-Accounts Payable", self.cc(), v, f"AP check {self._chk} - {v}", "AP", str(self._chk))
                clear = min(_bday_offset(d, self.rng.randint(2, 9)), BDAYS[-1])
                sid = self.bank(clear, clear, a, f"CHECK {self._chk}", "", str(self._chk), "CHECK")
                self.truth("exact_check", sid, gid)
            else:  # issued late in the month, not yet presented
                d = self.day(-9)
                gid = self.gl(d, a, "2000-Accounts Payable", self.cc(), v, f"AP check {self._chk} - {v}", "AP", str(self._chk))
                self.truth("outstanding_check", gid=gid)

    def ap_ach(self, exact=560, timing=220, messy=110):
        for i in range(exact + timing + messy):
            v = self.rng.choice(VENDORS)
            a = -self.amt(80, 60000)
            d = self.day(0, -3)
            ref = _ref("ACH", self.rng)
            if i < exact:
                gid = self.gl(d, a, "2000-Accounts Payable", self.cc(), v, f"ACH payment {ref}", "AP", ref)
                post = _bday_offset(d, self.rng.choice([0, 0, 1]))
                sid = self.bank(d, post, a, f"ACH DEBIT {bank_clean_name(v)} {ref}", bank_clean_name(v), ref, "ACH_DEBIT")
                self.truth("exact_ach", sid, gid)
            elif i < exact + timing:  # bank strips our reference; posts 1-3 business days later
                gid = self.gl(d, a, "2000-Accounts Payable", self.cc(), v, f"ACH payment {ref}", "AP", ref)
                post = _bday_offset(d, self.rng.randint(1, 3))
                sid = self.bank(post, post, a, f"ACH DEBIT {bank_clean_name(v)} PPD", bank_clean_name(v), "", "ACH_DEBIT")
                self.truth("timing_difference", sid, gid)
            else:  # card / processor debit with a messy payee string
                gid = self.gl(d, a, "2100-Accrued Expenses", self.cc(), v, f"Vendor card/online payment - {v}", "AP", "")
                post = _bday_offset(d, self.rng.randint(0, 4))
                nm = bank_messy_name(v, self.rng)
                sid = self.bank(post, post, a, f"POS DEBIT {nm}", nm, "", "CARD_DEBIT")
                self.truth("messy_payee", sid, gid)

    def recurring_subscriptions(self):
        """Same vendor, same amount, several times a month - tests 1:1 matching."""
        subs = [("Amazon Web Services", -2480.00), ("Microsoft Corporation", -1312.50),
                ("Zoom Video Communications", -499.00), ("Adobe Inc", -899.99),
                ("Granite Ridge Properties", -18500.00)]
        for v, a in subs:
            n = 1 if "Properties" in v else 4
            for k in range(n):
                d = BDAYS[min(k * 5 + 1, len(BDAYS) - 4)]
                ref = _ref("ACH", self.rng)
                gid = self.gl(d, a, "6100-Rent & Subscriptions", "CC500-IT", v, f"Recurring {v} #{k+1}", "AP", ref)
                post = _bday_offset(d, self.rng.randint(0, 2))
                nm = bank_clean_name(v)
                sid = self.bank(post, post, a, f"ACH DEBIT {nm}", nm, "", "ACH_DEBIT")
                self.truth("recurring_same_amount", sid, gid)

    def wires_out(self, n=110):
        for _ in range(n):
            v = self.rng.choice(VENDORS[32:])
            a = -self.amt(5000, 250000)
            d = self.day(0, -2)
            ref = _ref("FW", self.rng, 10)
            gid = self.gl(d, a, "2000-Accounts Payable", self.cc(), v, f"Outgoing wire {ref}", "TR", ref)
            sid = self.bank(d, d, a, f"WIRE OUT {bank_clean_name(v)} FED REF {ref}", bank_clean_name(v), ref, "WIRE_OUT")
            self.truth("exact_wire", sid, gid)

    def customer_receipts(self, exact=500, timing=170, messy=80, short_paid=18, dit=24, splits=12):
        for i in range(exact + timing + messy + short_paid):
            c = self.rng.choice(CUSTOMERS)
            a = self.amt(400, 180000)
            d = self.day(0, -3)
            ref = _ref("INV", self.rng, 6)
            if i < exact:
                gid = self.gl(d, a, "1200-Accounts Receivable", "CC400-Sales", c, f"Customer receipt {ref}", "AR", ref)
                sid = self.bank(d, _bday_offset(d, self.rng.choice([0, 1])), a,
                                f"ACH CREDIT {bank_clean_name(c)} {ref}", bank_clean_name(c), ref, "ACH_CREDIT")
                self.truth("exact_receipt", sid, gid)
            elif i < exact + timing:
                gid = self.gl(d, a, "1200-Accounts Receivable", "CC400-Sales", c, f"Customer receipt {ref}", "AR", ref)
                post = _bday_offset(d, self.rng.randint(1, 3))
                sid = self.bank(post, post, a, f"ACH CREDIT {bank_clean_name(c)} CCD", bank_clean_name(c), "", "ACH_CREDIT")
                self.truth("timing_difference", sid, gid)
            elif i < exact + timing + messy:
                gid = self.gl(d, a, "1200-Accounts Receivable", "CC400-Sales", c, f"Customer receipt {ref}", "AR", ref)
                post = _bday_offset(d, self.rng.randint(0, 4))
                nm = bank_messy_name(c, self.rng)
                sid = self.bank(post, post, a, f"DEPOSIT {nm}", nm, "", "DEPOSIT")
                self.truth("messy_payee", sid, gid)
            else:  # incoming wire short-paid by an intermediary bank fee
                fee = self.rng.choice([15.0, 20.0, 25.0, 35.0])
                gid = self.gl(d, a, "1200-Accounts Receivable", "CC400-Sales", c, f"Wire receipt {ref}", "AR", ref)
                sid = self.bank(d, d, a - fee, f"WIRE IN {bank_clean_name(c)} OBI {ref}", bank_clean_name(c), "", "WIRE_IN")
                self.truth("amount_mismatch", sid, gid)
        for _ in range(dit):  # deposits booked on the last 2 days, not yet credited by the bank
            c = self.rng.choice(CUSTOMERS)
            gid = self.gl(self.day(-2), self.amt(1000, 90000), "1200-Accounts Receivable", "CC400-Sales", c,
                          f"Remote deposit capture {_ref('RDC', self.rng, 6)}", "AR")
            self.truth("deposit_in_transit", gid=gid)
        for _ in range(splits):  # customer pays two invoices in one bank credit
            c = self.rng.choice(CUSTOMERS)
            d = self.day(0, -3)
            a1, a2 = self.amt(500, 40000), self.amt(500, 40000)
            g1 = self.gl(d, a1, "1200-Accounts Receivable", "CC400-Sales", c, f"Invoice {_ref('INV', self.rng, 6)}", "AR")
            g2 = self.gl(d, a2, "1200-Accounts Receivable", "CC400-Sales", c, f"Invoice {_ref('INV', self.rng, 6)}", "AR")
            post = _bday_offset(d, 1)
            sid = self.bank(post, post, a1 + a2, f"ACH CREDIT {bank_clean_name(c)} CCD", bank_clean_name(c), "", "ACH_CREDIT")
            self.truth("split_payment", sid, f"{g1}|{g2}")

    def lockbox(self, n=240):
        for _ in range(n):
            d = self.day(0, -2)
            a = self.amt(800, 120000)
            ref = _ref("LBX", self.rng, 6)
            gid = self.gl(d, a, "1200-Accounts Receivable", "CC400-Sales", "Lockbox batch", f"Lockbox batch {ref}", "AR", ref)
            sid = self.bank(d, d, a, f"LOCKBOX DEPOSIT {ref}", "LOCKBOX", ref, "DEPOSIT")
            self.truth("exact_lockbox", sid, gid)

    def card_settlements(self):
        for proc, gl_name, lo, hi in [("STRIPE TRANSFER", "Stripe", 2000, 26000),
                                      ("AMEX SETTLEMENT", "Amex Settlement", 1500, 18000)]:
            for d in BDAYS[:-2]:
                a = self.amt(lo, hi)
                gid = self.gl(d, a, "4000-Revenue", "CC400-Sales", gl_name, f"Card settlement {d:%m/%d}", "AR")
                post = _bday_offset(d, self.rng.randint(1, 2))
                sid = self.bank(post, post, a, f"{proc} ST-{_ref('', self.rng, 6)}", proc, "", "CARD_SETTLEMENT")
                self.truth("card_settlement", sid, gid)

    def payroll(self):
        for pay in [pd.Timestamp("2026-10-09"), pd.Timestamp("2026-10-23")]:
            for name, lo, hi, acct in [("ADP WAGE PAY", 610000, 640000, "2300-Payroll Clearing"),
                                       ("ADP TAX", 190000, 205000, "2310-Payroll Taxes Payable"),
                                       ("ADP 401K", 38000, 42000, "2320-401k Payable")]:
                a = -self.amt(lo, hi)
                ref = _ref("ADP", self.rng, 7)
                gid = self.gl(pay, a, acct, "CC100-Admin", "ADP Payroll", f"Payroll {pay:%m/%d} - {name}", "PR", ref)
                sid = self.bank(pay, pay, a, f"{name} {ref}", name, ref, "PAYROLL")
                self.truth("exact_payroll", sid, gid)

    def bank_only_items(self):
        # Monthly analysis fee & interest are booked in GL by a recurring JE -> they DO match
        fee = -1847.35
        gid = self.gl(BDAYS[-1], fee, "6150-Bank Charges", "CC100-Admin", "Bank", "Accrued account analysis fee", "GL")
        sid = self.bank(BDAYS[-1], BDAYS[-1], fee, "ACCOUNT ANALYSIS FEE OCT", "BANK", "", "FEE")
        self.truth("booked_bank_fee", sid, gid)
        # Bank-only: wire fees, interest, NSF returned items + fees, chargebacks
        for _ in range(38):
            d = self.day()
            self.truth("bank_fee", self.bank(d, d, -self.rng.choice([18.0, 25.0, 45.0]), "INTL WIRE FEE", "BANK", "", "FEE"))
        self.truth("interest", self.bank(BDAYS[-1], BDAYS[-1], 1236.48, "INTEREST PAID", "BANK", "", "INTEREST"))
        for _ in range(7):
            d = self.day(3)
            c = self.rng.choice(CUSTOMERS)
            self.truth("nsf_return", self.bank(d, d, -self.amt(900, 22000), f"RETURNED ITEM NSF {bank_clean_name(c)}",
                                               bank_clean_name(c), "", "NSF"))
            self.truth("nsf_fee", self.bank(d, d, -36.0, "RETURNED ITEM FEE", "BANK", "", "FEE"))
        for _ in range(14):
            d = self.day()
            self.truth("chargeback", self.bank(d, d, -self.amt(60, 4500), f"CHARGEBACK CB-{_ref('', self.rng, 7)}",
                                               "STRIPE", "", "CHARGEBACK"))
        self.truth("chargeback_fee", self.bank(BDAYS[-1], BDAYS[-1], -14 * 15.0, "CHARGEBACK FEES 14 @ 15.00", "STRIPE", "", "FEE"))

    def duplicate_postings(self, n=9):
        """An AP payment keyed twice in the GL: one line matches, the copy stays open."""
        matched = [g for g in self.b.gl if g["source"] == "AP" and g["reference"].startswith("ACH")]
        for g in self.rng.sample(matched, n):
            gid = self.gl(pd.Timestamp(g["gl_date"]), g["amount"], g["offset_account"], g["cost_center"],
                          g["counterparty"], g["memo"] + " (re-keyed)", "AP", "")
            self.truth("duplicate_posting", gid=gid)

    def run(self):
        self.ap_checks()
        self.ap_ach()
        self.recurring_subscriptions()
        self.wires_out()
        self.customer_receipts()
        self.lockbox()
        self.card_settlements()
        self.payroll()
        self.bank_only_items()
        self.duplicate_postings()
        bank = pd.DataFrame(self.b.bank)
        gl = pd.DataFrame(self.b.gl)
        # Shuffle into date order like a real statement / GL detail report
        bank = bank.sort_values(["posted_date", "statement_id"]).reset_index(drop=True)
        gl = gl.sort_values(["gl_date", "gl_id"]).reset_index(drop=True)
        return bank, gl, pd.DataFrame(self.b.truth)


def generate(out_dir: str | Path = "data", seed: int = SEED):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    bank, gl, truth = Generator(seed).run()
    bank.to_csv(out / "bank_statement.csv", index=False)
    gl.to_csv(out / "general_ledger.csv", index=False)
    truth.to_csv(out / "ground_truth.csv", index=False)
    return bank, gl, truth


if __name__ == "__main__":
    b, g, t = generate()
    print(f"bank lines: {len(b):,}  GL lines: {len(g):,}")
