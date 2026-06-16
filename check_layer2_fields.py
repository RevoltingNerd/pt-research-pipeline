"""
check_layer2_fields.py — Scan Layer 2 output JSONs for missing or empty
fields across stage_outputs, to spot whether qwen3.6 systematically drops
certain keys from larger JSON schemas (Stage 4 / Stage 6 in particular).

Usage:
    python3 check_layer2_fields.py [glob_pattern]

Default glob: summaries/deep/*_layer2.json
(adjust if your Layer 2 outputs land in a different directory/naming pattern)
"""

import json
import sys
from pathlib import Path

# Fields flagged from the first article (42245972) as blank/missing
FLAGGED_FIELDS = {
    's4': ['generalizability_rationale'],
    's6': ['power_adequate', 'limitations_reflected_in_conclusion'],
}

# Full expected schema per stage (from the stage prompt files), for a
# broader sweep beyond just the flagged fields.
EXPECTED_FIELDS = {
    's1': ['signal_present', 'sample_size', 'intervention', 'comparator',
           'primary_outcome', 'primary_result', 'study_design',
           'clinical_domain', 'ai_tool', 'signal_quality_note'],
    's2': ['randomization', 'allocation_concealment', 'blinding',
           'blinding_detail', 'baseline_homogeneity', 'dropout_rate',
           'intention_to_treat', 'follow_up_duration',
           'primary_methodology_strength', 'primary_methodology_weakness',
           'bias_risk_structured'],
    's3': ['oxford_level', 'oxford_roman', 'oxford_rationale', 'downgraded',
           'downgrade_reason', 'clinical_necessity', 'necessity_rationale'],
    's4': ['population', 'clinical_setting', 'geographic_context',
           'inclusion_criteria', 'exclusion_criteria',
           'confounders_identified', 'generalizability',
           'generalizability_rationale'],
    's5': ['conclusion_claim', 'actual_primary_result',
           'confidence_interval_reported', 'ci_width',
           'statistical_significance', 'clinical_significance',
           'spin_detected', 'spin_detail', 'implementation_result',
           'clinician_role', 'effect_size_summary'],
    's6': ['power_analysis_reported', 'power_adequate', 'limitations_stated',
           'limitations_content', 'limitations_reflected_in_conclusion',
           'internal_consistency', 'scope_of_practice', 'output_validation',
           'guardrails_safety', 'accountability_liability',
           'training_competency', 'governance_overall_summary',
           'patient_safety_concerns', 'ethical_considerations',
           'implementation_barriers', 'future_research_stated'],
    's7': ['key_takeaway', 'evidence_statement', 'grade_risk_of_bias',
           'grade_indirectness', 'grade_imprecision', 'governance_synthesis',
           'symposium_relevance', 'appraisal_confidence',
           'appraisal_confidence_rationale'],
}

DIMENSION_KEYS = ['scope_of_practice', 'output_validation', 'guardrails_safety',
                  'accountability_liability', 'training_competency']


def is_blank(val):
    if val is None:
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    return False


def check_file(path: Path):
    data = json.loads(path.read_text())
    stages = data.get('stage_outputs', {})
    issues = []

    for stage_key, fields in EXPECTED_FIELDS.items():
        stage_data = stages.get(stage_key)
        if stage_data is None:
            issues.append(f"{stage_key}: ENTIRE STAGE MISSING")
            continue
        for field in fields:
            if field not in stage_data:
                issues.append(f"{stage_key}.{field}: MISSING (key absent)")
            elif field in DIMENSION_KEYS:
                # these are dicts with status/detail
                entry = stage_data[field]
                if not isinstance(entry, dict):
                    issues.append(f"{stage_key}.{field}: malformed (not a dict)")
                elif is_blank(entry.get('status')):
                    issues.append(f"{stage_key}.{field}.status: BLANK")
            else:
                if is_blank(stage_data[field]):
                    issues.append(f"{stage_key}.{field}: BLANK (empty string)")

    return issues


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "summaries/deep/*_layer2.json"
    files = sorted(Path('.').glob(pattern))

    if not files:
        # try a few common alternate locations
        for alt in ["summaries/deep/*_qwen36full.json", "*_layer2.json",
                     "summaries/*_layer2.json"]:
            files = sorted(Path('.').glob(alt))
            if files:
                print(f"(no match for '{pattern}', using '{alt}' instead)\n")
                break

    if not files:
        print(f"No files found matching '{pattern}' or fallbacks. "
              f"Pass the correct glob as an argument.")
        return

    print(f"Checking {len(files)} files\n")

    # Track frequency of each issue across the corpus
    from collections import Counter
    issue_freq = Counter()
    per_file_issues = {}

    for f in files:
        try:
            issues = check_file(f)
        except Exception as e:
            print(f"{f.name}: ERROR reading/parsing — {e}")
            continue

        per_file_issues[f.name] = issues
        for issue in issues:
            # normalize to drop per-article specifics, keep field path
            issue_freq[issue] += 1

    # Per-file report
    print("="*70)
    print("PER-FILE ISSUES")
    print("="*70)
    for fname, issues in per_file_issues.items():
        if issues:
            print(f"\n{fname}:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"\n{fname}: clean (no missing/blank fields)")

    # Aggregate report
    print("\n" + "="*70)
    print("AGGREGATE — fields blank/missing across corpus")
    print("="*70)
    if not issue_freq:
        print("No issues found across any file.")
    else:
        for issue, count in issue_freq.most_common():
            print(f"  {count}/{len(files)}  {issue}")

    # Specifically call out the flagged fields
    print("\n" + "="*70)
    print("FLAGGED FIELDS FROM ARTICLE 42245972 — corpus-wide status")
    print("="*70)
    for stage_key, fields in FLAGGED_FIELDS.items():
        for field in fields:
            matches = [k for k in issue_freq if k.startswith(f"{stage_key}.{field}")]
            total = sum(issue_freq[k] for k in matches)
            print(f"  {stage_key}.{field}: blank/missing in {total}/{len(files)} articles")


if __name__ == '__main__':
    main()
