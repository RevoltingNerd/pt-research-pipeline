# PT Research Pipeline v3 — Future Directions
## Binary-First Extraction Architecture with Algorithmic GRADE Assessment
### Draft for Methods Paper — Future Directions Section
### RevoltingNerd · June 2026

---

## Overview

Pipeline v2 demonstrated that automated evidence synthesis is feasible,
reproducible, and clinically useful across multiple rehabilitation corpora.
The primary architectural limitation identified during validation is that
the model performs dual roles simultaneously: **extraction** (reading text
and retrieving structured data) and **judgment** (interpreting that data
to produce quality ratings). These roles have fundamentally different
reliability profiles and should be separated.

V3 proposes a **binary-first extraction architecture** in which the
language model functions exclusively as a transducer — text in, structured
binary data out — and all quality assessment logic moves into deterministic
Python post-processing. This directly addresses the scholarly consensus
that AI is not ready for autonomous GRADE assessment (Hultcrantz et al.,
2025; Taneri et al., 2025) while preserving the efficiency gains of
automated screening and data extraction.

The critical distinction: the scholarly critique applies to models making
**judgment calls**. It does not apply to models performing **structured
extraction** of reported facts. V3 is designed to keep the model
exclusively in the extraction role.

---

## Architectural Comparison

| Component | V2 (Current) | V3 (Proposed) |
|---|---|---|
| Oxford Level | Model assigns from study design text | Lookup table: design string → Roman numeral |
| Bias Risk | Model judges "low/moderate/high" | Weighted sum of binary flags |
| GRADE Certainty | Model synthesizes per cluster | Deterministic algorithm from extracted fields |
| Spin Detection | Model judges conclusion vs results | Hybrid: binary flags + targeted model call |
| MCID Comparison | 25-measure YAML (manual) | 600+ measure RMD-derived database |
| Reproducibility | Probabilistic (model weights) | Deterministic (Python logic) |
| Audit Trail | Justification text fields | Specific flag that triggered each decision |
| Adjustability | Requires prompt retuning | Change one line of Python |

---

## Part I: Extraction Schema

The v3 extraction prompt asks the model to populate a single JSON object
per article. No interpretation, no evaluation, no synthesis. If a field
is not reported in the article, the model outputs `null`. The prompt
contains zero judgment language.

### 1.1 Study Identity & Design

```json
{
  "pmid": "string",
  "title": "string",
  "authors": ["string"],
  "journal": "string",
  "year": "integer",
  "doi": "string",

  "study_design_raw": "string — verbatim as reported by authors",
  "study_design_normalized": "string — one of: rct, quasi_rct, cluster_rct,
    crossover_rct, systematic_review, meta_analysis, scoping_review,
    narrative_review, prospective_cohort, retrospective_cohort,
    case_control, cross_sectional, case_series, case_report,
    feasibility_study, pilot_rct, protocol, expert_opinion, other",

  "pre_registered": "0|1|null",
  "registration_number": "string|null",
  "industry_funded": "0|1|null",
  "conflict_of_interest_reported": "0|1",
  "sample_size_total": "integer|null",
  "sample_size_per_arm": "integer|null",
  "dropout_rate_pct": "float|null",
  "intention_to_treat_analysis": "0|1|null"
}
```

### 1.2 Population & Intervention

```json
{
  "clinical_population": "string — verbatim diagnosis or condition",
  "population_age_group": "pediatric|adult|geriatric|mixed|null",
  "setting": "inpatient|outpatient|community|telehealth|laboratory|null",
  "intervention_name": "string",
  "intervention_type": "string — one of: robotic, wearable_sensor, llm,
    clinical_decision_support, telerehabilitation, ai_diagnosis,
    ai_documentation, ai_outcome_prediction, gamified_rehab,
    exoskeleton, bci, other",
  "comparator": "string|null",
  "comparator_type": "standard_care|sham|waitlist|active|no_control|null",
  "follow_up_duration_weeks": "integer|null"
}
```

### 1.3 Bias Assessment Flags

```json
{
  "was_randomized": "0|1",
  "allocation_concealed": "0|1|null",
  "blinding_participants": "0|1|null",
  "blinding_assessors": "0|1|null",
  "blinding_care_providers": "0|1|null",
  "selective_outcome_reporting": "0|1|null",
  "baseline_characteristics_comparable": "0|1|null",
  "attrition_bias_present": "0|1|null",
  "fidelity_reported": "0|1|null",
  "protocol_fully_specified": "0|1"
}
```

### 1.4 Outcome Measures & Results

```json
{
  "primary_outcome_measure_name": "string",
  "primary_outcome_measure_abbreviation": "string|null",
  "primary_outcome_between_group_delta": "float|null",
  "primary_outcome_ci_lower": "float|null",
  "primary_outcome_ci_upper": "float|null",
  "ci_crosses_null": "0|1|null",
  "primary_outcome_p_value": "float|null",
  "primary_outcome_p_significant": "0|1|null",
  "effect_size_value": "float|null",
  "effect_size_type": "cohens_d|hedges_g|odds_ratio|risk_ratio|
    mean_difference|standardized_mean_difference|null",
  "secondary_outcomes": [
    {
      "measure_name": "string",
      "between_group_delta": "float|null",
      "p_significant": "0|1|null"
    }
  ],
  "surrogate_outcome_used": "0|1",
  "patient_reported_outcome": "0|1",
  "objective_outcome": "0|1"
}
```

### 1.5 Evidence Consistency Flags (cluster-level, populated in post-processing)

```json
{
  "heterogeneity_reported": "0|1|null",
  "i_squared_pct": "float|null",
  "direction_consistent_with_cluster": "0|1|null",
  "n_studies_in_cluster": "integer"
}
```

### 1.6 Indirectness Flags

```json
{
  "population_matches_research_question": "0|1",
  "intervention_matches_research_question": "0|1",
  "outcome_matches_research_question": "0|1",
  "results_applicable_to_clinical_practice": "0|1|null"
}
```

### 1.7 Spin Detection (hybrid — only fields requiring model judgment)

```json
{
  "author_conclusion_verbatim": "string — exact conclusion sentence(s)",
  "primary_outcome_p_significant": "0|1|null",
  "mcid_met": "0|1|null",
  "conclusion_claims_efficacy": "0|1",
  "conclusion_claims_causation": "0|1",
  "conclusion_language_exceeds_design": "0|1",
  "abstract_matches_results": "0|1"
}
```

*Note: `conclusion_claims_efficacy`, `conclusion_claims_causation`,
`conclusion_language_exceeds_design`, and `abstract_matches_results`
are the only fields requiring model judgment. All others are factual
extraction. Spin score is calculated algorithmically from these four
flags plus the statistical fields.*

### 1.8 Governance Flags

```json
{
  "scope_of_practice_addressed": "implemented|aspirational|not_addressed",
  "output_validation_addressed": "implemented|aspirational|not_addressed",
  "safety_guardrails_addressed": "implemented|aspirational|not_addressed",
  "accountability_liability_addressed": "implemented|aspirational|not_addressed",
  "training_competency_addressed": "implemented|aspirational|not_addressed",
  "regulatory_framework_cited": "0|1",
  "patient_consent_for_ai_discussed": "0|1"
}
```

---

## Part II: Algorithmic GRADE Module

All GRADE logic lives in `grade.py`. No model calls. Fully deterministic.
Every downgrade decision is logged with the specific flag that triggered it.

### 2.1 Study Design → Starting GRADE Level

```python
DESIGN_TO_GRADE = {
    # High — controlled experimental designs
    "systematic_review":    "High",
    "meta_analysis":        "High",
    "rct":                  "High",
    "cluster_rct":          "High",
    "crossover_rct":        "High",
    "pilot_rct":            "Moderate",  # pilot designs start one level lower

    # Low — observational designs
    "prospective_cohort":   "Low",
    "retrospective_cohort": "Low",
    "case_control":         "Low",
    "cross_sectional":      "Low",
    "quasi_rct":            "Low",

    # Very Low — descriptive / opinion
    "case_series":          "Very Low",
    "case_report":          "Very Low",
    "feasibility_study":    "Very Low",
    "narrative_review":     "Very Low",
    "scoping_review":       "Very Low",
    "protocol":             "Very Low",
    "expert_opinion":       "Very Low",
    "other":                "Very Low",
}

GRADE_LEVELS = ["Very Low", "Low", "Moderate", "High"]
```

### 2.2 Risk of Bias Assessment

```python
def assess_risk_of_bias(article: dict) -> tuple[int, list[str]]:
    """
    Returns (downgrade_levels, reasons_list)
    Downgrade 0, 1, or 2 levels based on binary flags.
    Every decision is logged to reasons_list for audit trail.
    """
    flags_failed = []

    if article.get("was_randomized") == 0:
        flags_failed.append("not_randomized")
    if article.get("allocation_concealed") == 0:
        flags_failed.append("allocation_not_concealed")
    if article.get("blinding_participants") == 0:
        flags_failed.append("participants_not_blinded")
    if article.get("blinding_assessors") == 0:
        flags_failed.append("assessors_not_blinded")
    if article.get("intention_to_treat_analysis") == 0:
        flags_failed.append("no_intention_to_treat")
    if article.get("attrition_bias_present") == 1:
        flags_failed.append("attrition_bias_present")
    if article.get("selective_outcome_reporting") == 1:
        flags_failed.append("selective_outcome_reporting")

    dropout = article.get("dropout_rate_pct")
    if dropout is not None and dropout > 20:
        flags_failed.append(f"dropout_rate_{dropout:.0f}pct_exceeds_threshold")

    n_flags = len(flags_failed)
    if n_flags >= 4:
        return 2, flags_failed
    elif n_flags >= 2:
        return 1, flags_failed
    else:
        return 0, flags_failed
```

### 2.3 Inconsistency Assessment

```python
def assess_inconsistency(article: dict) -> tuple[int, list[str]]:
    reasons = []
    n_studies = article.get("n_studies_in_cluster", 1)

    if n_studies <= 1:
        return 0, ["single_study_inconsistency_not_applicable"]

    i_squared = article.get("i_squared_pct")
    direction = article.get("direction_consistent_with_cluster")

    if i_squared is not None and i_squared > 75:
        reasons.append(f"high_heterogeneity_i2_{i_squared:.0f}pct")
        return 2, reasons
    elif i_squared is not None and i_squared > 50:
        reasons.append(f"moderate_heterogeneity_i2_{i_squared:.0f}pct")
        return 1, reasons
    elif direction == 0:
        reasons.append("inconsistent_direction_of_effect_across_cluster")
        return 1, reasons

    return 0, reasons
```

### 2.4 Indirectness Assessment

```python
def assess_indirectness(article: dict) -> tuple[int, list[str]]:
    reasons = []

    if article.get("population_matches_research_question") == 0:
        reasons.append("population_indirect")
    if article.get("intervention_matches_research_question") == 0:
        reasons.append("intervention_indirect")
    if article.get("outcome_matches_research_question") == 0:
        reasons.append("outcome_indirect")
    if article.get("surrogate_outcome_used") == 1:
        reasons.append("surrogate_outcome_used")

    n_flags = len(reasons)
    if n_flags >= 2:
        return 2, reasons
    elif n_flags == 1:
        return 1, reasons
    return 0, reasons
```

### 2.5 Imprecision Assessment

```python
# Optimal Information Size thresholds by outcome type
OIS_THRESHOLDS = {
    "dichotomous": 300,   # events
    "continuous":  200,   # participants
    "default":     200,
}

def assess_imprecision(article: dict) -> tuple[int, list[str]]:
    reasons = []
    n = article.get("sample_size_total") or 0
    ci_crosses = article.get("ci_crosses_null")
    ci_reported = article.get("confidence_interval_reported", 0)
    threshold = OIS_THRESHOLDS["default"]

    if not ci_reported:
        reasons.append("confidence_interval_not_reported")

    if ci_crosses == 1:
        reasons.append("confidence_interval_crosses_null")
        if n < threshold:
            reasons.append(f"sample_size_{n}_below_ois_threshold_{threshold}")
            return 2, reasons
        return 1, reasons

    if n < threshold:
        reasons.append(f"sample_size_{n}_below_ois_threshold_{threshold}")
        return 1, reasons

    return 0, reasons
```

### 2.6 Publication Bias Assessment

```python
def assess_publication_bias(article: dict,
                             cluster_articles: list) -> tuple[int, list[str]]:
    reasons = []
    n_in_cluster = len(cluster_articles)

    industry_funded = article.get("industry_funded", 0)
    grey_searched = any(
        a.get("grey_literature_searched", 0) for a in cluster_articles
    )

    if n_in_cluster >= 10 and not grey_searched:
        reasons.append(
            f"funnel_plot_asymmetry_possible_{n_in_cluster}_studies_"
            f"no_grey_literature_search"
        )
        return 1, reasons

    if industry_funded and n_in_cluster < 5:
        reasons.append("industry_funded_small_cluster_publication_bias_suspected")
        return 1, reasons

    return 0, reasons
```

### 2.7 Upgrade Factors

```python
def assess_upgrade_factors(article: dict) -> tuple[int, list[str]]:
    reasons = []
    upgrades = 0

    effect = article.get("effect_size_value")
    effect_type = article.get("effect_size_type", "")

    if effect is not None:
        if effect_type in ("odds_ratio", "risk_ratio") and effect >= 5.0:
            reasons.append(f"very_large_effect_{effect_type}_{effect:.1f}")
            upgrades += 2
        elif effect_type in ("odds_ratio", "risk_ratio") and effect >= 2.0:
            reasons.append(f"large_effect_{effect_type}_{effect:.1f}")
            upgrades += 1
        elif effect_type in ("cohens_d", "hedges_g") and abs(effect) >= 1.2:
            reasons.append(f"very_large_effect_d_{effect:.2f}")
            upgrades += 2
        elif effect_type in ("cohens_d", "hedges_g") and abs(effect) >= 0.8:
            reasons.append(f"large_effect_d_{effect:.2f}")
            upgrades += 1

    if article.get("dose_response_reported") == 1:
        reasons.append("dose_response_gradient_present")
        upgrades += 1

    return upgrades, reasons
```

### 2.8 Master GRADE Calculator

```python
def calculate_grade(article: dict,
                    cluster_articles: list) -> dict:
    """
    Calculates GRADE certainty level for a single article.
    Returns full audit trail — every decision with its triggering flag.
    """
    design = article.get("study_design_normalized", "other")
    starting_level = DESIGN_TO_GRADE.get(design, "Very Low")
    starting_idx   = GRADE_LEVELS.index(starting_level)

    # Assess all five downgrade domains
    rob_down,  rob_reasons  = assess_risk_of_bias(article)
    inc_down,  inc_reasons  = assess_inconsistency(article)
    ind_down,  ind_reasons  = assess_indirectness(article)
    imp_down,  imp_reasons  = assess_imprecision(article)
    pub_down,  pub_reasons  = assess_publication_bias(article, cluster_articles)

    # Assess upgrade factors
    upgrades, up_reasons = assess_upgrade_factors(article)

    total_down = rob_down + inc_down + ind_down + imp_down + pub_down
    final_idx  = max(0, min(3, starting_idx - total_down + upgrades))
    final_level = GRADE_LEVELS[final_idx]

    return {
        "pmid":                article.get("pmid"),
        "grade_certainty":     final_level,
        "starting_level":      starting_level,
        "total_downgrades":    total_down,
        "total_upgrades":      upgrades,
        "audit_trail": {
            "risk_of_bias": {
                "downgrade_levels": rob_down,
                "flags": rob_reasons
            },
            "inconsistency": {
                "downgrade_levels": inc_down,
                "flags": inc_reasons
            },
            "indirectness": {
                "downgrade_levels": ind_down,
                "flags": ind_reasons
            },
            "imprecision": {
                "downgrade_levels": imp_down,
                "flags": imp_reasons
            },
            "publication_bias": {
                "downgrade_levels": pub_down,
                "flags": pub_reasons
            },
            "upgrade_factors": {
                "upgrade_levels": upgrades,
                "flags": up_reasons
            }
        }
    }
```

---

## Part III: MCID Database Expansion

The current `mcid_reference.yaml` contains 25 manually curated measures.
V3 proposes expanding this to 600+ measures using the Shirley Ryan
AbilityLab Rehabilitation Measures Database (sralab.org/rehabilitation-measures)
as the primary source.

### 3.1 Proposed Schema

```yaml
# mcid_reference_v3.yaml
# Source: Rehabilitation Measures Database, Shirley Ryan AbilityLab
# Last updated: [date]
# Format: measure_name, abbreviation(s), mcid_value, mcid_source, domain, population

measures:
  - name: "Oswestry Disability Index"
    abbreviations: ["ODI"]
    mcid_absolute: 10.0
    mcid_percent: 30.0
    mdc: 10.0
    source: "Fritz JM & Irrgang JJ, 2001. Phys Ther. doi:10.1093/ptj/81.2.776"
    rmd_url: "https://www.sralab.org/rehabilitation-measures/oswestry-disability-index"
    domain: "spine"
    population: "adult"
    measure_type: "patient_reported"
    score_range: [0, 100]
    better_direction: "lower"

  - name: "Fugl-Meyer Assessment Upper Extremity"
    abbreviations: ["FMA-UE", "FMA"]
    mcid_absolute: 5.25
    mcid_percent: null
    mdc: 7.25
    source: "Page SJ et al., 2012. Neurorehabil Neural Repair."
    rmd_url: "https://www.sralab.org/rehabilitation-measures/fugl-meyer-assessment-upper-extremity"
    domain: "neurological"
    population: "adult_stroke"
    measure_type: "clinician_reported"
    score_range: [0, 66]
    better_direction: "higher"

  # ... 600+ additional measures
```

### 3.2 Data Collection Strategy

Rather than manual curation, v3 proposes a one-time structured extraction
from the RMD using the following approach:

1. Pull the RMD measure list (600+ instruments)
2. For each measure, extract: name, abbreviations, MCID, MDC, source citation,
   clinical domain, population, score range, direction of improvement
3. Validate against source publications for measures used in > 5 pipeline runs
4. Store as a versioned YAML with citation trail

This is a research assistant task, not a pipeline task — done once,
maintained quarterly.

---

## Part IV: Spin Detection V3

Spin detection is the one component where the model retains a judgment
role in v3, but it is substantially constrained.

### 4.1 Hybrid Architecture

**Algorithmic layer (Python — no model):**
```python
def calculate_spin_score(article: dict) -> dict:
    flags = []
    score = 0

    # Statistical mismatch flags
    if (article.get("conclusion_claims_efficacy") == 1 and
            article.get("primary_outcome_p_significant") == 0):
        flags.append("efficacy_claimed_without_significance")
        score += 3

    if (article.get("conclusion_claims_efficacy") == 1 and
            article.get("mcid_met") == 0):
        flags.append("efficacy_claimed_without_mcid")
        score += 2

    if article.get("conclusion_claims_causation") == 1:
        design = article.get("study_design_normalized", "")
        if design not in ("rct", "cluster_rct", "crossover_rct",
                          "systematic_review", "meta_analysis"):
            flags.append("causal_claim_from_observational_design")
            score += 3

    if article.get("conclusion_language_exceeds_design") == 1:
        flags.append("conclusion_language_exceeds_study_design")
        score += 2

    if article.get("abstract_matches_results") == 0:
        flags.append("abstract_disconnect_from_results")
        score += 2

    spin_detected = score >= 3
    return {
        "spin_detected": spin_detected,
        "spin_score": score,
        "spin_flags": flags
    }
```

**Model layer (targeted — only when needed):**
The model is only called for spin assessment when `spin_score` is 1-2
(borderline). At score 0 (no flags) and score 3+ (clear spin), the
algorithmic layer is authoritative. The model call for borderline cases
uses a tightly constrained prompt:

> "The following article concluded: [author_conclusion_verbatim].
> The primary outcome p-value was [p_value]. The MCID was [met/not met].
> The study design was [design].
> Answer only: Does the conclusion overstate what these results support?
> Answer: YES or NO. One word only."

Temperature: 0.0. No explanation requested. Binary output only.

---

## Part V: V3 Project Structure

```
pt_research_pipeline_v3/
├── extract.py              # model as transducer — binary JSON per article
├── grade.py                # deterministic GRADE from binary flags
├── oxford.py               # lookup table: design string → Roman numeral
├── spin.py                 # hybrid algorithmic + targeted model call
├── mcid.py                 # MCID lookup against expanded RMD database
├── cluster.py              # dynamic clustering (same as v2)
├── report.py               # output generation
├── prompts/
│   ├── extract.txt         # single extraction prompt — no judgment language
│   └── spin_borderline.txt # targeted binary spin prompt
├── schemas/
│   ├── extraction.json     # JSON Schema for validation + null checking
│   ├── study_designs.yaml  # design string normalization lookup
│   ├── oxford_lookup.yaml  # design → Oxford level
│   └── consort_strobe.yaml # reporting checklist items → bias flags
└── data/
    ├── mcid_reference_v3.yaml   # 600+ measures from RMD
    └── grade_thresholds.yaml    # OIS thresholds, i² cutoffs, configurable
```

---

## Part VI: Validation Strategy

### V3 vs V2 Comparison Study (proposed)

1. Run both pipelines on the pelvic floor PT corpus (99 articles, validated)
2. Compare GRADE certainty outputs article by article
3. Where they agree: confidence is high
4. Where they diverge: identify which specific binary flag triggered the
   v3 divergence — this is the audit trail that v2 cannot provide
5. Calculate Cohen's kappa for GRADE agreement between v2 and v3
6. For a sample of 30 articles: compare both pipeline outputs against
   two independent human raters using the same Oxford and GRADE criteria
7. Report κ (pipeline vs human) for: Oxford level, bias risk, GRADE certainty,
   spin detection

### IRR Validation Protocol (proposed)

- N = 30 articles selected from pelvic floor corpus
  (stratified by Oxford level and GRADE certainty)
- Rater 1: PT clinician with systematic review training
- Rater 2: PT researcher with GRADE methodology experience
- Both raters blind to pipeline outputs
- Ratings: Oxford level (I-V), bias risk (low/moderate/high),
  GRADE certainty (High/Moderate/Low/Very Low), spin (yes/no)
- Pipeline outputs compared to human consensus rating
- Report κ per domain, overall accuracy, false positive/negative rates
  for spin detection

---

## Part VII: Anticipated Improvements Over V2

| Metric | V2 Expected | V3 Expected | Basis |
|---|---|---|---|
| Oxford Level IRR vs human | κ ≈ 0.55–0.65 | κ ≈ 0.80–0.90 | Lookup table removes model variability |
| GRADE Certainty reproducibility | ~85% same-article | ~100% | Deterministic algorithm |
| Spin detection precision | ~70% | ~75–80% | Algorithmic pre-filter reduces false positives |
| Audit trail specificity | Justification text | Specific flag per decision | Binary feature vector |
| MCID coverage | 25 measures | 600+ measures | RMD database expansion |
| Run reproducibility | Probabilistic | Deterministic | No judgment in extraction |

---

## Summary for Paper — Future Directions Paragraph

> The primary architectural limitation of Pipeline v2 is the co-location
> of extraction and judgment within a single model call. Future work should
> separate these roles: the language model functions exclusively as a
> transducer, converting article text into a structured binary feature
> vector, while all quality assessment logic — Oxford level assignment,
> bias risk aggregation, GRADE certainty calculation, and spin scoring —
> moves into deterministic Python post-processing. This binary-first
> architecture addresses the scholarly consensus that AI models are not
> ready for autonomous GRADE assessment (Hultcrantz et al., 2025) while
> preserving the efficiency gains demonstrated in this pipeline. Every
> quality assessment decision becomes traceable to a specific extracted
> flag, rendering the audit trail fully explicit and adjustable without
> model retuning. Expansion of the MCID reference database from 25 to
> 600+ measures using the Rehabilitation Measures Database (Shirley Ryan
> AbilityLab) is a natural extension that would substantially improve
> clinical leverage scoring coverage across rehabilitation disciplines.
> A formal inter-rater reliability study comparing pipeline outputs against
> trained human raters across Oxford level, bias risk, GRADE certainty,
> and spin detection domains would provide the validation evidence required
> for broader adoption in systematic review methodology.

---

*PT Research Pipeline v3 — Future Directions Draft*
*github.com/RevoltingNerd/pt-research-pipeline*
*DOI: 10.5281/zenodo.20822054*
*June 2026*
