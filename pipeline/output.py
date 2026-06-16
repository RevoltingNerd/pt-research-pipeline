"""
output.py — Stage 6: Output
PT Research Pipeline

Appends new and updated records to the ledger CSV.
Generates a markdown summary document per appraised article.
Never overwrites existing ledger rows — updates in place by PMID.
"""

import pandas as pd
import logging
import os
from datetime import date, datetime

log = logging.getLogger(__name__)


def write_article_to_ledger(article: dict, ledger: pd.DataFrame,
                             ledger_path: str, run_id: str) -> pd.DataFrame:
    """
    Upsert a single article record into the ledger DataFrame.
    Writes the updated DataFrame to disk.
    Returns the updated DataFrame.
    """
    pmid      = str(article["pmid"])
    today     = date.today().isoformat()

    row = {
        "pmid":                  pmid,
        "feed_source":           article.get("feed_source", ""),
        "first_seen_date":       today,        # Only set on first insert
        "last_processed_date":   today,
        "title":                 article.get("title", ""),
        "authors":               article.get("authors", ""),
        "journal":               article.get("journal", ""),
        "publication_year":      article.get("publication_year", ""),
        "doi":                   article.get("doi", ""),
        "pmcid":                 article.get("pmcid", ""),
        "article_type":          article.get("article_type", ""),
        "mesh_terms":            article.get("mesh_terms", ""),
        "abstract":              article.get("abstract", ""),
        "full_text_available":   article.get("full_text_available", False),
        "reprocess_pending":     article.get("reprocess_pending", True),
        "fetch_error":           article.get("fetch_error", ""),
        "pdf_path":              article.get("pdf_path", ""),
        "appraisal_complete":    article.get("appraisal_complete", False),
        "oxford_level":          article.get("oxford_level", ""),
        "mcdermott_grade":       article.get("mcdermott_grade", ""),
        "relevance_to_pq":       article.get("relevance_to_pq", ""),
        "implementation_result": article.get("implementation_result", ""),
        "summary_path":          article.get("summary_path", ""),
        "appraisal_confidence":  article.get("appraisal_confidence", ""),
        "model_used":            article.get("model_used", ""),
        "run_id":                run_id,
    }

    # Check if PMID already exists
    if not ledger.empty and pmid in ledger["pmid"].astype(str).values:
        # Preserve original first_seen_date
        existing_row  = ledger[ledger["pmid"].astype(str) == pmid]
        original_date = existing_row["first_seen_date"].values[0]
        row["first_seen_date"] = original_date

        # Update existing row
        mask = ledger["pmid"].astype(str) == pmid
        for col, val in row.items():
            if col in ledger.columns:
                ledger.loc[mask, col] = val
        log.debug(f"PMID {pmid}: ledger row updated")
    else:
        # Append new row
        new_df = pd.DataFrame([row])
        ledger = pd.concat([ledger, new_df], ignore_index=True)
        log.debug(f"PMID {pmid}: new ledger row added")

    # Write to disk after every article — protects against mid-run failure
    _save_ledger(ledger, ledger_path)
    return ledger


def write_summary(article: dict, paths_cfg: dict, appraisal_cfg: dict) -> str:
    """
    Generate a markdown summary document for an appraised article.
    Returns the path to the written file, or empty string on failure.
    Only runs if appraisal_complete is True.
    """
    if not article.get("appraisal_complete", False):
        return ""

    pmid          = article["pmid"]
    summaries_dir = paths_cfg.get("summaries", "summaries/")
    appraisal     = article.get("_appraisal_data", {})

    if not appraisal:
        log.warning(f"PMID {pmid}: no appraisal data — summary not generated")
        return ""

    os.makedirs(summaries_dir, exist_ok=True)
    summary_path = os.path.join(summaries_dir, f"{pmid}_summary.md")

    try:
        content = _build_summary_markdown(article, appraisal)
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(content)
        log.info(f"PMID {pmid}: summary written to {summary_path}")
        return summary_path

    except Exception as e:
        log.error(f"PMID {pmid}: summary write failed: {e}")
        return ""


def _build_summary_markdown(article: dict, appraisal: dict) -> str:
    """Build the full markdown content for an article summary."""

    pmid    = article.get("pmid", "")
    conf    = appraisal.get("appraisal_confidence", "")
    notes   = appraisal.get("appraisal_notes", "none")
    today   = datetime.now().strftime("%Y-%m-%d")

    # Confidence flag
    conf_flag = ""
    if conf == "low":
        conf_flag = "\n> ⚠️ **Low appraisal confidence** — review this article manually before citing.\n"

    # Evidence badge line
    oxford      = appraisal.get("oxford_level", "?")
    mcdermott   = appraisal.get("mcdermott_grade", "?")
    relevance   = appraisal.get("relevance_to_primary_question", "?")
    impl_result = appraisal.get("implementation_result", "not_reported")

    md = f"""# {article.get("title", "Untitled")}

**PMID:** {pmid}  
**Authors:** {article.get("authors", "Not available")}  
**Journal:** {article.get("journal", "Not available")} ({article.get("publication_year", "")})  
**DOI:** {article.get("doi", "Not available")}  
**Article type:** {article.get("article_type", "Not available")}  
**Feed source:** {article.get("feed_source", "")}  
**Appraised:** {today} · **Model:** {article.get("model_used", "")}

---

## Evidence grade

| Field | Value |
|-------|-------|
| Oxford OCEBM level | **{oxford}** |
| McDermott grade | **{mcdermott}** |
| Relevance to primary question | {relevance} |
| Implementation result | {impl_result} |
| Appraisal confidence | {conf} |

{conf_flag}

---

## Clinician summary

{appraisal.get("clinician_summary", "Not available")}

---

## Study details

**Study design:** {appraisal.get("study_design", "Not reported")}

**Oxford level rationale:** {appraisal.get("oxford_level_rationale", "")}

**McDermott grade rationale:** {appraisal.get("mcdermott_grade_rationale", "")}

**Clinical context:** {appraisal.get("clinical_context", "Not reported")}

**AI tool studied:** {appraisal.get("ai_tool_described", "Not specified")}

**Population:** {appraisal.get("population", "Not reported")}

**Outcome measures:** {appraisal.get("outcome_measures", "Not reported")}

---

## Implementation findings

**Result:** {impl_result}

{appraisal.get("implementation_detail", "Not reported")}

**Clinician role retained vs delegated:** {appraisal.get("clinician_role", "Not reported")}

---

## Governance and safety

**Governance recommendations:** {appraisal.get("governance_recommendations", "None stated")}

**Patient safety concerns:** {appraisal.get("patient_safety_concerns", "None stated")}

---

## Appraisal notes

{notes if notes and notes.lower() != "none" else "No flags."}

---

## MeSH terms

{article.get("mesh_terms", "Not available")}

---

*Generated by PT Research Pipeline — evidence grade assigned by AI appraisal (Llama 3 via Ollama). All grades should be verified by a qualified clinician before clinical application.*
"""
    return md.strip()


def _save_ledger(ledger: pd.DataFrame, ledger_path: str) -> None:
    """Write ledger DataFrame to CSV. Creates parent directory if needed."""
    try:
        os.makedirs(os.path.dirname(ledger_path) if os.path.dirname(ledger_path) else ".", exist_ok=True)
        ledger.to_csv(ledger_path, index=False)
    except Exception as e:
        log.error(f"Failed to save ledger to {ledger_path}: {e}")
        raise


def write_run_digest(
    run_id: str,
    run_stats: dict,
    appraised_articles: list[dict],
    paths_cfg: dict,
    appraisal_cfg: dict,
) -> str:
    """
    Write a digest markdown file summarising the current run.
    Contains stats, new articles processed, and a table of appraised articles.
    This file is the candidate for Teams delivery in Phase 3.
    """
    logs_dir  = paths_cfg.get("logs", "logs/")
    today     = datetime.now().strftime("%Y-%m-%d")
    digest_path = os.path.join(logs_dir, f"digest_{today}.md")

    min_relevance = appraisal_cfg.get("min_relevance_for_digest", "moderate")
    include_low_conf = appraisal_cfg.get("include_low_confidence_in_digest", True)

    # Filter articles for digest
    relevance_order = {"high": 0, "moderate": 1, "low": 2}
    threshold = relevance_order.get(min_relevance, 1)

    digest_articles = []
    for a in appraised_articles:
        rel = a.get("relevance_to_pq", "low")
        if relevance_order.get(rel, 2) <= threshold:
            if not include_low_conf and a.get("appraisal_confidence") == "low":
                continue
            digest_articles.append(a)

    # Sort by relevance then evidence level
    digest_articles.sort(key=lambda x: (
        relevance_order.get(x.get("relevance_to_pq", "low"), 2),
        x.get("oxford_level", "5"),
    ))

    lines = [
        f"# PT Research Pipeline — Weekly Digest",
        f"",
        f"**Run date:** {today}  ",
        f"**Run ID:** {run_id}",
        f"",
        f"---",
        f"",
        f"## Run summary",
        f"",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Feeds processed | {run_stats.get('feeds_processed', 0)} |",
        f"| New articles ingested | {run_stats.get('new_articles', 0)} |",
        f"| Reprocess attempts | {run_stats.get('reprocess_attempts', 0)} |",
        f"| Full text acquired | {run_stats.get('full_text_acquired', 0)} |",
        f"| Appraisals completed | {run_stats.get('appraisals_completed', 0)} |",
        f"| Skipped (paywall/no PMC) | {run_stats.get('skipped', 0)} |",
        f"| Errors | {run_stats.get('errors', 0)} |",
        f"",
        f"---",
        f"",
        f"## Appraised articles this run",
        f"",
    ]

    if not digest_articles:
        lines.append("No new appraised articles meet the digest threshold this run.")
    else:
        lines += [
            f"| Title | Oxford | McDermott | Relevance | Impl. result | Summary path |",
            f"|-------|--------|-----------|-----------|--------------|--------------|",
        ]
        for a in digest_articles:
            title   = (a.get("title") or "")[:60] + ("…" if len(a.get("title", "")) > 60 else "")
            conf_marker = " ⚠️" if a.get("appraisal_confidence") == "low" else ""
            lines.append(
                f"| {title}{conf_marker} | {a.get('oxford_level', '')} | "
                f"{a.get('mcdermott_grade', '')} | {a.get('relevance_to_pq', '')} | "
                f"{a.get('implementation_result', '')} | "
                f"[summary]({a.get('summary_path', '')}) |"
            )

    lines += [
        f"",
        f"---",
        f"",
        f"*PT Research Pipeline · evidence synthesis for responsible AI development in physical therapy*",
    ]

    os.makedirs(logs_dir, exist_ok=True)
    try:
        with open(digest_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        log.info(f"Run digest written: {digest_path}")
        return digest_path
    except Exception as e:
        log.error(f"Digest write failed: {e}")
        return ""
