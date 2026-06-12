"""
run_backfill.py — Step 4: Metadata backfill
PT Research Pipeline v2

Fetches authors, journal, year, and DOI from PubMed E-utilities for every
article in summaries/deep/ and overwrites any nan/empty values in the JSON
files. Runs automatically between Layer 2 and Layer 3 clustering.

Safe to re-run — only updates fields that are currently nan or empty.

Usage:
    python3 run_backfill.py
"""

import json
import logging
import os
import sys
import time
import yaml
import requests
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))
os.chdir(PIPELINE_ROOT)

LOG_PATH = Path(f"logs/backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
LOG_PATH.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH)]
)
log = logging.getLogger(__name__)


def fetch_batch(pmids: list, base_url: str, email: str) -> dict:
    params = {
        "db":      "pubmed",
        "id":      ",".join(pmids),
        "retmode": "xml",
        "rettype": "full",
        "email":   email,
    }
    try:
        r = requests.get(f"{base_url}/efetch.fcgi", params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        log.error(f"Fetch failed: {e}")
        return {}

    out = {}
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID", "")
        if not pmid:
            continue
        try:
            # Title
            tel   = art.find(".//ArticleTitle")
            title = "".join(tel.itertext()).strip() if tel is not None else ""

            # Authors
            authors = []
            for a in art.findall(".//AuthorList/Author"):
                ln  = a.findtext("LastName", "")
                fn  = a.findtext("ForeName", "") or a.findtext("Initials", "")
                col = a.findtext("CollectiveName", "")
                if ln:    authors.append(f"{ln} {fn}".strip())
                elif col: authors.append(col)
            auth_str = ", ".join(authors[:3])
            if len(authors) > 3:
                auth_str += " et al."

            # Journal
            journal = (
                art.findtext(".//Journal/Title", "") or
                art.findtext(".//Journal/ISOAbbreviation", "") or
                art.findtext(".//MedlineJournalInfo/MedlineTA", "")
            )

            # Year
            year = (
                art.findtext(".//Journal/JournalIssue/PubDate/Year", "") or
                art.findtext(".//ArticleDate/Year", "") or
                (art.findtext(".//PubDate/MedlineDate", "") or "")[:4]
            )

            # DOI
            doi = ""
            for el in art.findall(".//ArticleId"):
                if el.get("IdType") == "doi":
                    doi = el.text or ""
                    break

            out[pmid] = {
                "title":            title,
                "authors":          auth_str,
                "journal":          journal,
                "publication_year": year,
                "doi":              doi,
            }
        except Exception as e:
            log.warning(f"Parse error for PMID {pmid}: {e}")

    return out


def needs_backfill(data: dict) -> bool:
    """Return True if any core metadata field is missing or nan."""
    for field in ["authors", "journal", "publication_year"]:
        val = str(data.get(field, ""))
        if val in ("", "nan", "None", "none", "NaN"):
            return True
    return False


def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    api_cfg  = cfg.get("pubmed_api", {})
    base_url = api_cfg.get("base_url", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils")
    email    = api_cfg.get("email", "")

    deep  = Path("summaries/deep")
    jsons = sorted(deep.glob("*_layer2.json"))

    if not jsons:
        log.warning("No Layer 2 JSON files found — skipping backfill")
        return

    # Find articles that need backfill
    needs = []
    for f in jsons:
        data = json.loads(f.read_text())
        if needs_backfill(data):
            needs.append((f, data))

    log.info(f"Articles needing metadata backfill: {len(needs)} of {len(jsons)}")

    if not needs:
        log.info("All metadata already populated — nothing to do")
        return

    # Fetch in batches of 10
    pmids   = [str(d.get("pmid", "")) for _, d in needs]
    pmids   = [p for p in pmids if p]
    all_meta = {}

    for i in range(0, len(pmids), 10):
        batch = pmids[i:i+10]
        log.info(f"  Fetching {i+1}–{i+len(batch)} of {len(pmids)}...")
        meta = fetch_batch(batch, base_url, email)
        all_meta.update(meta)
        time.sleep(0.4)   # be polite to NCBI

    log.info(f"Metadata fetched for {len(all_meta)} articles")

    # Spot-check
    for pmid in list(all_meta.keys())[:3]:
        m = all_meta[pmid]
        log.info(f"  {pmid}: {m['authors'][:40]} | {m['journal'][:25]} | {m['publication_year']}")

    # Write back to JSON files
    updated = 0
    for f, data in needs:
        pmid = str(data.get("pmid", ""))
        if pmid not in all_meta:
            continue
        meta    = all_meta[pmid]
        changed = False
        for field in ["title", "authors", "journal", "publication_year", "doi"]:
            current = str(data.get(field, ""))
            new_val = meta.get(field, "")
            if new_val and current in ("", "nan", "None", "none", "NaN"):
                data[field] = new_val
                changed = True
        if changed:
            f.write_text(json.dumps(data, indent=2))
            updated += 1

    log.info(f"Updated {updated} JSON files")
    log.info("Metadata backfill complete")


if __name__ == "__main__":
    main()
