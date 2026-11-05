"""
Bank Reconciliation Auto-Matcher - end-to-end pipeline.

    python pipeline.py              # generate data, match, write Excel + charts
    python pipeline.py --no-generate  # reuse the CSVs already in data/
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src import charts
from src.excel_report import write_report
from src.generate_data import generate
from src.matcher import load_inputs, match

ROOT = Path(__file__).parent


def score_against_truth(result, truth_path):
    """Compare engine pairs to the generator's intended pairs (synthetic data only)."""
    t = pd.read_csv(truth_path)
    t = t[(t["statement_id"].notna()) & (t["gl_id"].notna()) & (~t["gl_id"].astype(str).str.contains(r"\|"))]
    truth = set(zip(t["statement_id"], t["gl_id"]))
    m = result.matches
    auto = m[m["match_status"].isin(["Exact", "Strong"])]
    correct = sum((s, g) in truth for s, g in zip(auto["statement_id"], auto["gl_id"]))
    return {"auto_cleared_precision": correct / len(auto) if len(auto) else 0.0,
            "pairs_recovered": len(set(zip(m["statement_id"], m["gl_id"])) & truth) / len(truth)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-generate", action="store_true", help="reuse existing data/*.csv")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    if not args.no_generate:
        generate(ROOT / "data", seed=args.seed)
    bank, gl = load_inputs(ROOT / "data")
    result = match(bank, gl)
    xlsx = write_report(result, ROOT / "output" / "reconciliation_report.xlsx")
    charts.make_all(result, ROOT / "docs" / "images")

    # Persist outputs so the Streamlit app starts instantly
    out = ROOT / "output"
    result.matches.to_csv(out / "matches.csv", index=False)
    result.unmatched_bank.to_csv(out / "unmatched_bank.csv", index=False)
    result.unmatched_gl.to_csv(out / "unmatched_gl.csv", index=False)
    k = dict(result.kpis)
    k.update(score_against_truth(result, ROOT / "data" / "ground_truth.csv"))
    (out / "kpis.json").write_text(json.dumps(k, indent=2))

    print("Bank Reconciliation Auto-Matcher — October 2026 (synthetic)")
    print(f"  Bank lines {k['bank_lines']:,} | GL lines {k['gl_lines']:,}")
    print(f"  Exact {k['exact']:,} | Strong {k['strong']:,} | Suggested {k['suggested']:,} | "
          f"Unmatched bank {k['unmatched_bank']:,} | Unmatched GL {k['unmatched_gl']:,}")
    print(f"  Match rate {k['match_rate_count']:.1%} by count, {k['match_rate_dollars']:.1%} by $ | "
          f"auto-cleared {k['auto_clear_rate_count']:.1%}")
    print(f"  Exceptions {k['exception_count']:,} items, ${k['exception_abs']:,.2f} absolute")
    print(f"  Auto-cleared precision vs ground truth {k['auto_cleared_precision']:.1%}")
    print(f"  Wrote {xlsx.relative_to(ROOT)} and charts in docs/images/")
    return result


if __name__ == "__main__":
    main()
