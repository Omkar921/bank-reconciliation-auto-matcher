"""Static chart images for the README (matplotlib)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

NAVY, TEAL, AMBER, RED, GREY, SLATE = "#1F3A5F", "#2A9D8F", "#E9C46A", "#E76F51", "#ADB5BD", "#6C757D"
STATUS_COLORS = {"Exact": NAVY, "Strong": TEAL, "Suggested": AMBER, "Unmatched-Bank": RED, "Unmatched-GL": SLATE}
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titleweight": "bold", "axes.titlesize": 13})


def _money(x, _=None):
    return f"${x/1e6:.1f}M" if abs(x) >= 1e6 else f"${x/1e3:.0f}K"


def match_mix(result, out):
    k = result.kpis
    labels = ["Exact", "Strong", "Suggested", "Unmatched-Bank", "Unmatched-GL"]
    vals = [k["exact"], k["strong"], k["suggested"], k["unmatched_bank"], k["unmatched_gl"]]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    bars = ax.barh(labels[::-1], vals[::-1], color=[STATUS_COLORS[x] for x in labels[::-1]])
    for b, v in zip(bars, vals[::-1]):
        ax.text(b.get_width() + 15, b.get_y() + b.get_height() / 2, f"{v:,}", va="center", fontsize=11)
    ax.set_title(f"Match status mix — {k['match_rate_count']:.1%} of bank lines matched")
    ax.set_xlabel("Lines")
    ax.set_xlim(0, max(vals) * 1.12)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def exception_dollars(result, out):
    ub, ug = result.unmatched_bank, result.unmatched_gl
    df = pd.concat([ub.assign(side="Bank"), ug.assign(side="GL")])
    s = df.assign(abs_amt=df["amount"].abs()).groupby("category")["abs_amt"].sum().sort_values()
    fig, ax = plt.subplots(figsize=(9, 4.8))
    colors = [RED if c in ub["category"].values and c not in ug["category"].values else SLATE for c in s.index]
    bars = ax.barh(s.index, s.values, color=colors)
    for b, v in zip(bars, s.values):
        ax.text(b.get_width(), b.get_y() + b.get_height() / 2, "  " + f"${v:,.0f}", va="center", fontsize=9)
    ax.xaxis.set_major_formatter(_money)
    ax.set_xlim(0, s.max() * 1.25)
    ax.set_title("Exception dollars by reconciling category")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=RED, label="Bank-side"), Patch(color=SLATE, label="Book-side / both")],
              loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def daily_unmatched(result, out):
    ub = result.unmatched_bank.assign(date=pd.to_datetime(result.unmatched_bank["posted_date"]))
    ug = result.unmatched_gl.assign(date=pd.to_datetime(result.unmatched_gl["gl_date"]))
    days = pd.date_range("2026-10-01", "2026-10-31")
    b = ub.groupby("date").size().reindex(days, fill_value=0)
    g = ug.groupby("date").size().reindex(days, fill_value=0)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.bar(days, b, color=RED, label="Unmatched bank", width=0.8)
    ax.bar(days, g, bottom=b, color=SLATE, label="Unmatched GL", width=0.8)
    ax.set_title("Open exceptions by date — month-end cut-off drives book-side items")
    ax.set_ylabel("Items")
    ax.legend(frameon=False)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d"))
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def payee_score_distribution(result, out):
    m = result.matches[result.matches["match_status"] != "Exact"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for st in ["Strong", "Suggested"]:
        ax.hist(m.loc[m["match_status"] == st, "payee_score"], bins=range(78, 102, 1), color=STATUS_COLORS[st],
                label=st, alpha=0.9)
    ax.axvline(90, color=NAVY, ls="--", lw=1)
    ax.axvline(80, color=AMBER, ls="--", lw=1)
    ax.text(90.3, ax.get_ylim()[1] * 0.9, "Strong ≥ 90", color=NAVY)
    ax.text(80.3, ax.get_ylim()[1] * 0.9, "Suggested ≥ 80", color="#B08900")
    ax.set_title("Fuzzy payee similarity of non-exact matches (rapidfuzz)")
    ax.set_xlabel("Payee score (0–100)")
    ax.set_ylabel("Matches")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def make_all(result, out_dir="docs/images"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "match_mix": out / "match_mix.png",
        "exception_dollars": out / "exception_dollars.png",
        "daily_unmatched": out / "daily_unmatched.png",
        "payee_scores": out / "payee_score_distribution.png",
    }
    match_mix(result, paths["match_mix"])
    exception_dollars(result, paths["exception_dollars"])
    daily_unmatched(result, paths["daily_unmatched"])
    payee_score_distribution(result, paths["payee_scores"])
    return paths
