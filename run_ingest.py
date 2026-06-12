"""
run_ingest.py — Step 1: Feed ingestion and ledger initialisation
PT Research Pipeline v2

Fetches all configured PubMed RSS feeds, deduplicates against the existing
ledger, fetches metadata and full text for new articles, and writes the
master ledger.csv.

This is the v2 ingest — replaces the v1 run.py/run_ingest.py which wired
directly into the old single-prompt appraisal. This script only ingests;
appraisal is handled by run_layer0.py, run_layer2.py, run_layer3_*.py.

Usage:
    python3 run_ingest.py           # all configured feeds
    python3 run_ingest.py --dry-run # fetch and dedup only, no full-text download
    python3 run_ingest.py --pmid 12345678  # single PMID (bypasses feeds)
    python3 run_ingest.py --all     # alias for default (kept for run_all.py compat)
"""

import argparse
import json
import logging
import os
import sys
import yaml
from datetime import datetime, date
from pathlib import Path

import pandas as pd

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))
os.chdir(PIPELINE_ROOT)

from pipeline.ingest import fetch_feed, fetch_pubmed_metadata, fetch_abstract_and_mesh
from pipeline.dedup  import load_ledger, filter_new_articles
from pipeline.fetch  import fetch_full_text

LOG_PATH = Path(f"logs/ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
LOG_PATH.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH)]
)
log = logging.getLogger(__name__)

LEDGER_COLS = [
    "pmid", "feed_source", "first_seen_date", "last_processed_date",
    "title", "authors", "journal", "publication_year", "doi", "pmcid",
    "article_type", "mesh_terms", "abstract",
    "full_text_available", "full_text_path", "fetch_error",
    "reprocess_pending", "run_date",
]


def upsert_ledger(ledger: pd.DataFrame, article: dict) -> pd.DataFrame:
    pmid  = str(article["pmid"])
    today = date.today().isoformat()

    row = {col: "" for col in LEDGER_COLS}
    row.update({
        "pmid":                pmid,
        "feed_source":         article.get("feed_source", ""),
        "first_seen_date":     today,
        "last_processed_date": today,
        "title":               article.get("title", ""),
        "authors":             article.get("authors", ""),
        "journal":             article.get("journal", ""),
        "publication_year":    article.get("publication_year", ""),
        "doi":                 article.get("doi", ""),
        "pmcid":               article.get("pmcid", ""),
        "article_type":        article.get("article_type", ""),
        "mesh_terms":          article.get("mesh_terms", ""),
        "abstract":            article.get("abstract", ""),
        "full_text_available": article.get("full_text_available", False),
        "full_text_path":      article.get("full_text_path", ""),
        "fetch_error":         article.get("fetch_error", ""),
        "reprocess_pending":   not article.get("full_text_available", False),
        "run_date":            today,
    })

    if not ledger.empty and pmid in ledger["pmid"].astype(str).values:
        mask = ledger["pmid"].astype(str) == pmid
        orig_date = ledger.loc[mask, "first_seen_date"].values[0]
        row["first_seen_date"] = orig_date
        for col, val in row.items():
            if col in ledger.columns:
                ledger.loc[mask, col] = val
    else:
        ledger = pd.concat([ledger, pd.DataFrame([row])], ignore_index=True)

    return ledger


def process_article(article: dict, cfg: dict, dry_run: bool = False) -> dict:
    pmid    = article["pmid"]
    api_cfg = cfg["pubmed_api"]

    # Fetch metadata
    if not article.get("title"):
        meta = fetch_pubmed_metadata([pmid], api_cfg)
        if pmid in meta:
            article.update(meta[pmid])

    if not article.get("abstract"):
        article.update(fetch_abstract_and_mesh(pmid, api_cfg))

    if dry_run:
        return article

    # Fetch full text
    article = fetch_full_text(article, cfg["paths"], api_cfg)
    return article


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pmid", type=str, default=None)
    parser.add_argument("--all",  action="store_true", help="Process all feeds (default)")
    args = parser.parse_args()

    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    for key, val in cfg["paths"].items():
        if not os.path.isabs(val):
            cfg["paths"][key] = str(PIPELINE_ROOT / val)

    topic_name   = cfg.get("topic", {}).get("short_name", "unknown topic")
    ledger_path  = cfg["paths"]["ledger"]
    ledger       = load_ledger(ledger_path)

    log.info("=" * 60)
    log.info(f"PT Research Pipeline v2 — Ingest")
    log.info(f"Topic: {topic_name}")
    log.info(f"Mode:  {'DRY RUN' if args.dry_run else 'SINGLE PMID' if args.pmid else 'ALL FEEDS'}")
    log.info("=" * 60)

    stats = {"feeds": 0, "new": 0, "skipped": 0, "full_text": 0, "errors": 0}

    # ── Single PMID mode ──────────────────────────────────────────────────────
    if args.pmid:
        log.info(f"Processing single PMID: {args.pmid}")
        article = {"pmid": args.pmid, "feed_source": "manual"}
        article = process_article(article, cfg, args.dry_run)
        ledger  = upsert_ledger(ledger, article)
        ledger.to_csv(ledger_path, index=False)
        log.info(f"PMID {args.pmid}: done — full_text={article.get('full_text_available')}")
        return

    # ── Feed mode ─────────────────────────────────────────────────────────────
    feeds = cfg.get("feeds", [])
    log.info(f"Feeds configured: {len(feeds)}")

    for feed_cfg in feeds:
        feed_name = feed_cfg.get("name", "unnamed")
        feed_url  = feed_cfg.get("url", "")

        if not feed_url or "PASTE_FEED" in feed_url:
            log.warning(f"Feed '{feed_name}': URL not configured — skipping")
            continue

        log.info(f"\nFeed: {feed_name} — {feed_cfg.get('description','')}")
        try:
            raw = fetch_feed(feed_cfg, cfg["pubmed_api"])
            log.info(f"  {len(raw)} articles from feed")

            dedup       = filter_new_articles(raw, ledger)
            new_articles = dedup["new"]
            stats["skipped"] += dedup.get("skip", 0)
            stats["new"]     += len(new_articles)
            log.info(f"  {len(new_articles)} new | {dedup.get('skip',0)} already in ledger")

            for article in new_articles:
                article["feed_source"] = feed_name
                try:
                    article = process_article(article, cfg, args.dry_run)
                    if article.get("full_text_available"):
                        stats["full_text"] += 1
                    ledger = upsert_ledger(ledger, article)
                    log.info(f"  PMID {article['pmid']}: ingested | "
                             f"full_text={article.get('full_text_available',False)}")
                except Exception as e:
                    log.error(f"  PMID {article.get('pmid','?')}: failed — {e}")
                    stats["errors"] += 1

            # Write ledger after each feed — crash protection
            ledger.to_csv(ledger_path, index=False)
            stats["feeds"] += 1

        except Exception as e:
            log.error(f"Feed '{feed_name}' failed: {e}", exc_info=True)
            stats["errors"] += 1

    log.info("\n" + "=" * 60)
    log.info("Ingest complete")
    log.info(f"  Feeds processed:  {stats['feeds']}")
    log.info(f"  New articles:     {stats['new']}")
    log.info(f"  Skipped (dedup):  {stats['skipped']}")
    log.info(f"  Full text found:  {stats['full_text']}")
    log.info(f"  Errors:           {stats['errors']}")
    log.info(f"  Ledger:           {ledger_path} ({len(ledger)} total rows)")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
