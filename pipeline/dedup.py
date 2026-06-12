"""
dedup.py — Stage 3: Deduplication
PT Research Pipeline

Compares incoming PMIDs against the ledger CSV.
Returns only articles not yet seen, or articles flagged for reprocessing.
Never modifies the ledger — read only. Ledger writes happen in output.py.
"""

import pandas as pd
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


def load_ledger(ledger_path: str) -> pd.DataFrame:
    if not os.path.exists(ledger_path):
        log.info("No ledger found — this appears to be the first run")
        return _empty_ledger()
    try:
        df = pd.read_csv(ledger_path, dtype=str)
        for col in ["full_text_available", "reprocess_pending", "appraisal_complete"]:
            if col in df.columns:
                df[col] = df[col].map(
                    {"True": True, "False": False, "true": True, "false": False}
                ).fillna(False)
        log.info(f"Ledger loaded: {len(df)} existing records")
        return df
    except Exception as e:
        log.error(f"Failed to load ledger from {ledger_path}: {e}")
        raise


def filter_new_articles(incoming: list[dict], ledger: pd.DataFrame) -> dict:
    if ledger.empty:
        existing_pmids = set()
        reprocess_pmids = set()
    else:
        existing_pmids = set(ledger["pmid"].astype(str).tolist())
        reprocess_pmids = set(
            ledger.loc[ledger["reprocess_pending"] == True, "pmid"]
            .astype(str).tolist()
        )

    new_articles = []
    reprocess_articles = []
    skip_count = 0

    for article in incoming:
        pmid = str(article["pmid"])
        if pmid not in existing_pmids:
            new_articles.append(article)
        elif pmid in reprocess_pmids:
            reprocess_articles.append(article)
        else:
            skip_count += 1

    log.info(
        f"Dedup results — new: {len(new_articles)}, "
        f"reprocess: {len(reprocess_articles)}, "
        f"skipped: {skip_count}"
    )
    return {"new": new_articles, "reprocess": reprocess_articles, "skip": skip_count}


def get_reprocess_candidates(ledger: pd.DataFrame) -> list[str]:
    if ledger.empty:
        return []
    mask = ledger["reprocess_pending"] == True
    candidates = ledger.loc[mask, "pmid"].astype(str).tolist()
    if candidates:
        log.info(f"Found {len(candidates)} articles pending reprocessing")
    return candidates


def _empty_ledger() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "pmid", "feed_source", "first_seen_date", "last_processed_date",
        "title", "authors", "journal", "publication_year", "doi", "pmcid",
        "article_type", "mesh_terms", "abstract", "full_text_available",
        "reprocess_pending", "fetch_error", "pdf_path", "appraisal_complete",
        "oxford_level", "mcdermott_grade", "relevance_to_pq",
        "implementation_result", "summary_path", "appraisal_confidence",
        "model_used", "run_id",
    ])
