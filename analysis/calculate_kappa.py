"""
calculate_kappa.py — Inter-Rater Reliability Calculator
PT Research Pipeline

Run this after both human raters have completed the annotation spreadsheet
and after AI grades have been compiled.

Usage:
    python3 calculate_kappa.py

Input: PT_IRR_Annotation_Tool.xlsx (Annotation Sheet tab)
       PT_Research_Evidence_Base.xlsx (AI grades from ledger)

Output: Kappa statistics for all comparisons printed to terminal
        and saved to irr_results.csv
"""

import pandas as pd
import numpy as np
from pathlib import Path


def cohen_kappa(rater1: list, rater2: list) -> dict:
    """
    Calculate Cohen's Kappa for two lists of categorical ratings.
    Returns kappa, percent agreement, and 95% confidence interval.
    """
    assert len(rater1) == len(rater2), "Rater lists must be same length"
    n = len(rater1)

    # Get all unique categories
    categories = sorted(set(rater1) | set(rater2))

    # Observed agreement
    agree = sum(r1 == r2 for r1, r2 in zip(rater1, rater2))
    po = agree / n

    # Expected agreement
    pe = 0
    for cat in categories:
        p1 = rater1.count(cat) / n
        p2 = rater2.count(cat) / n
        pe += p1 * p2

    # Kappa
    if pe == 1:
        kappa = 1.0
    else:
        kappa = (po - pe) / (1 - pe)

    # Standard error and 95% CI (Fleiss formula)
    se = np.sqrt((po * (1 - po)) / (n * (1 - pe) ** 2))
    ci_lower = kappa - 1.96 * se
    ci_upper = kappa + 1.96 * se

    # Interpretation
    if kappa < 0.20:
        interpretation = "Slight"
    elif kappa < 0.40:
        interpretation = "Fair"
    elif kappa < 0.60:
        interpretation = "Moderate"
    elif kappa < 0.80:
        interpretation = "Substantial"
    else:
        interpretation = "Almost perfect"

    return {
        "kappa":           round(kappa, 3),
        "percent_agree":   round(po * 100, 1),
        "ci_lower":        round(ci_lower, 3),
        "ci_upper":        round(ci_upper, 3),
        "n":               n,
        "interpretation":  interpretation,
    }


def interpret_kappa(k: dict) -> str:
    return (f"κ = {k['kappa']} ({k['interpretation']}) "
            f"[95% CI: {k['ci_lower']} – {k['ci_upper']}] "
            f"Agreement: {k['percent_agree']}% (n={k['n']})")


def main():
    print("=" * 70)
    print("PT Research Pipeline — Inter-Rater Reliability Calculator")
    print("=" * 70)

    # Load annotation spreadsheet
    ann_path = Path("PT_IRR_Annotation_Tool.xlsx")
    if not ann_path.exists():
        print(f"ERROR: {ann_path} not found in current directory")
        return

    try:
        df = pd.read_excel(ann_path, sheet_name="Annotation Sheet", header=0)
    except Exception as e:
        print(f"ERROR reading annotation sheet: {e}")
        return

    print(f"\nLoaded annotation sheet: {len(df)} rows")
    print(f"Columns: {list(df.columns)}")

    # Expected column names — adjust if your spreadsheet uses different names
    # These match the headers in the annotation tool
    PMID_COL        = "PMID"
    RATER1_OX_COL   = "Your Oxford Level\n(1a/1b/1c/2a/2b/2c/3a/3b/4/5)"
    RATER1_MC_COL   = "Your McDermott Grade\n(A/B/C/D)"

    # Check columns exist
    missing = [c for c in [PMID_COL, RATER1_OX_COL, RATER1_MC_COL] if c not in df.columns]
    if missing:
        print(f"\nWARNING: Could not find columns: {missing}")
        print("Available columns:", list(df.columns))
        print("\nPlease update the column name variables in this script to match your spreadsheet.")
        return

    # Clean data
    df = df.dropna(subset=[RATER1_OX_COL, RATER1_MC_COL])
    df[RATER1_OX_COL] = df[RATER1_OX_COL].astype(str).str.strip().str.lower()
    df[RATER1_MC_COL] = df[RATER1_MC_COL].astype(str).str.strip().str.upper()

    print(f"\nRater 1 completed: {len(df)} articles")

    # ── If Rater 2 data is in a second file or second set of columns ──────────
    # Add Rater 2 columns to the annotation sheet with headers:
    # "Rater 2 Oxford Level" and "Rater 2 McDermott Grade"
    # Then this script will calculate human-human Kappa

    RATER2_OX_COL = "Rater 2 Oxford Level"
    RATER2_MC_COL = "Rater 2 McDermott Grade"

    has_rater2 = (RATER2_OX_COL in df.columns and RATER2_MC_COL in df.columns)

    if has_rater2:
        df2 = df.dropna(subset=[RATER2_OX_COL, RATER2_MC_COL])
        df2[RATER2_OX_COL] = df2[RATER2_OX_COL].astype(str).str.strip().str.lower()
        df2[RATER2_MC_COL] = df2[RATER2_MC_COL].astype(str).str.strip().str.upper()
        print(f"Rater 2 completed: {len(df2)} articles")
    else:
        print("\nRater 2 columns not found yet — add them when Rater 2 is done.")
        print("Expected column names: 'Rater 2 Oxford Level' and 'Rater 2 McDermott Grade'")

    # ── Load AI grades from ledger ─────────────────────────────────────────────
    ledger_path = Path("ledger.csv")
    if not ledger_path.exists():
        print("\nWARNING: ledger.csv not found — cannot calculate human-AI Kappa")
        ai_df = None
    else:
        ai_df = pd.read_csv(ledger_path, dtype=str)
        ai_df['pmid'] = ai_df['pmid'].astype(str).str.strip()
        ai_df['oxford_level'] = ai_df['oxford_level'].astype(str).str.strip().str.lower()
        ai_df['mcdermott_grade'] = ai_df['mcdermott_grade'].astype(str).str.strip().str.upper()

    # ── Merge AI grades with annotation ───────────────────────────────────────
    if ai_df is not None:
        df['pmid_str'] = df[PMID_COL].astype(str).str.strip()
        merged = df.merge(
            ai_df[['pmid', 'oxford_level', 'mcdermott_grade']],
            left_on='pmid_str', right_on='pmid', how='left'
        )
        has_ai = merged['oxford_level'].notna().sum() > 0
        print(f"\nAI grades matched: {merged['oxford_level'].notna().sum()} / {len(merged)} articles")
    else:
        merged = df.copy()
        has_ai = False

    # ── Calculate Kappa values ─────────────────────────────────────────────────
    results = []
    print("\n" + "=" * 70)
    print("KAPPA RESULTS")
    print("=" * 70)

    # Human-Human
    if has_rater2:
        common = df2.merge(df, on=PMID_COL, suffixes=('_r2', '_r1'))
        if len(common) >= 10:
            r1_ox = common[f"{RATER1_OX_COL}_r1"].tolist()
            r2_ox = common[f"{RATER2_OX_COL}"].tolist()
            r1_mc = common[f"{RATER1_MC_COL}_r1"].tolist()
            r2_mc = common[f"{RATER2_MC_COL}"].tolist()

            k_ox = cohen_kappa(r1_ox, r2_ox)
            k_mc = cohen_kappa(r1_mc, r2_mc)

            print(f"\nHuman Rater 1 vs Human Rater 2:")
            print(f"  Oxford:    {interpret_kappa(k_ox)}")
            print(f"  McDermott: {interpret_kappa(k_mc)}")
            results.append({"comparison": "Rater1 vs Rater2", "oxford_kappa": k_ox['kappa'],
                            "mcdermott_kappa": k_mc['kappa'], "n": k_ox['n']})

    # Rater 1 vs AI
    if has_ai:
        r1_merged = merged.dropna(subset=['oxford_level', RATER1_OX_COL])
        if len(r1_merged) >= 10:
            r1_ox = r1_merged[RATER1_OX_COL].tolist()
            ai_ox = r1_merged['oxford_level'].tolist()
            r1_mc = r1_merged[RATER1_MC_COL].tolist()
            ai_mc = r1_merged['mcdermott_grade'].tolist()

            k_ox = cohen_kappa(r1_ox, ai_ox)
            k_mc = cohen_kappa(r1_mc, ai_mc)

            print(f"\nHuman Rater 1 vs AI:")
            print(f"  Oxford:    {interpret_kappa(k_ox)}")
            print(f"  McDermott: {interpret_kappa(k_mc)}")
            results.append({"comparison": "Rater1 vs AI", "oxford_kappa": k_ox['kappa'],
                            "mcdermott_kappa": k_mc['kappa'], "n": k_ox['n']})

    if not results:
        print("\nNo Kappa values calculated yet.")
        print("Complete the annotation spreadsheet and run this script again.")
        print("\nTo add Rater 2 grades:")
        print("  1. Open PT_IRR_Annotation_Tool.xlsx")
        print("  2. Add columns 'Rater 2 Oxford Level' and 'Rater 2 McDermott Grade'")
        print("  3. Enter Rater 2's grades")
        print("  4. Re-run this script")
        return

    # Save results
    results_df = pd.DataFrame(results)
    results_df.to_csv("irr_results.csv", index=False)
    print(f"\nResults saved to irr_results.csv")

    print("\n" + "=" * 70)
    print("REPORTING TEMPLATE (copy into Methods section)")
    print("=" * 70)
    print("""
Inter-rater reliability was assessed using Cohen's Kappa statistic
for Oxford OCEBM level assignment and McDermott grade assignment
independently. A random sample of 30 articles (22% of the corpus,
seed = 42) was independently appraised by two human raters blinded
to AI-generated grades and to each other's assessments.
Kappa values were interpreted as: <0.20 slight, 0.21-0.40 fair,
0.41-0.60 moderate, 0.61-0.80 substantial, >0.80 almost perfect
(Landis & Koch, 1977).
    """)


if __name__ == "__main__":
    main()
