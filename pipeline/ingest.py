"""
ingest.py — Stage 2: PubMed RSS ingest
PT Research Pipeline
"""

import feedparser
import requests
import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional

log = logging.getLogger(__name__)


def fetch_feed(feed_cfg: dict, api_cfg: dict) -> list[dict]:
    feed_name = feed_cfg["name"]
    rss_url = feed_cfg.get("url", feed_cfg.get("rss_url", ""))  # config uses "url"
    articles = []

    if rss_url and "PASTE_FEED" not in rss_url and "REPLACE_WITH" not in rss_url:
        log.info(f"[{feed_name}] Fetching via RSS: {rss_url}")
        articles = _fetch_rss(rss_url, feed_name)

    if not articles:
        log.info(f"[{feed_name}] RSS unavailable or empty — falling back to E-utilities")
        articles = _fetch_esearch(feed_cfg, api_cfg)

    log.info(f"[{feed_name}] Ingest complete: {len(articles)} articles retrieved")
    return articles


def _fetch_rss(url: str, feed_name: str) -> list[dict]:
    try:
        parsed = feedparser.parse(url)
        if parsed.bozo:
            log.warning(f"RSS parse warning for {feed_name}: {parsed.bozo_exception}")
        articles = []
        for entry in parsed.entries:
            pmid = _extract_pmid_from_entry(entry)
            if pmid:
                articles.append({"pmid": pmid, "title": entry.get("title", "").strip(), "feed_source": feed_name})
            else:
                log.debug(f"Could not extract PMID from entry: {entry.get('title', '')[:60]}")
        return articles
    except Exception as e:
        log.error(f"RSS fetch failed for {feed_name}: {e}")
        return []


def _extract_pmid_from_entry(entry) -> Optional[str]:
    entry_id = entry.get("id", "")
    if "/pubmed/" in entry_id:
        pmid = entry_id.split("/pubmed/")[-1].strip("/")
        if pmid.isdigit():
            return pmid
    link = entry.get("link", "")
    if "/pubmed/" in link:
        pmid = link.split("/pubmed/")[-1].strip("/").split("?")[0]
        if pmid.isdigit():
            return pmid
    for tag in entry.get("tags", []):
        term = tag.get("term", "")
        if term.isdigit():
            return term
    return None


def _fetch_esearch(feed_cfg: dict, api_cfg: dict) -> list[dict]:
    feed_name  = feed_cfg["name"]
    params_cfg = feed_cfg.get("esearch_params", {})
    base_url   = feed_cfg.get("esearch_url", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
    api_key    = api_cfg.get("api_key", "")
    delay      = api_cfg.get("request_delay", 0.4)

    # retmax_total controls the overall cap (default 300, max 10000)
    # E-utilities paginates in batches of up to 500
    total_target = int(params_cfg.get("retmax_total", params_cfg.get("retmax", "300")))
    batch_size   = min(500, total_target)

    all_ids = []
    retstart = 0

    while retstart < total_target:
        fetch_n = min(batch_size, total_target - retstart)
        params = {
            "db":         params_cfg.get("db", "pubmed"),
            "term":       params_cfg.get("term", ""),
            "retmax":     str(fetch_n),
            "retstart":   str(retstart),
            "retmode":    "json",
            "usehistory": "n",
        }
        if api_key:
            params["api_key"] = api_key

        try:
            time.sleep(delay)
            resp = requests.get(base_url, params=params, timeout=30)
            resp.raise_for_status()
            data    = resp.json()
            result  = data.get("esearchresult", {})
            id_list = result.get("idlist", [])
            count   = int(result.get("count", 0))

            if not id_list:
                break

            all_ids.extend(id_list)
            retstart += len(id_list)

            # Stop if we've retrieved everything available
            if retstart >= count:
                break

            log.info(f"[{feed_name}] E-utilities page: {len(all_ids)}/{min(total_target, count)} PMIDs retrieved")

        except Exception as e:
            log.error(f"E-utilities fetch failed for {feed_name} at retstart={retstart}: {e}")
            break

    log.info(f"[{feed_name}] E-utilities returned {len(all_ids)} PMIDs total")
    return [{"pmid": pmid, "title": "", "feed_source": feed_name} for pmid in all_ids]


def fetch_pubmed_metadata(pmids: list[str], api_cfg: dict) -> dict[str, dict]:
    if not pmids:
        return {}

    base_url = api_cfg.get("esummary_url", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi")
    api_key  = api_cfg.get("api_key", "")
    delay    = api_cfg.get("request_delay", 0.4)
    results  = {}
    batch_size = 20

    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i + batch_size]
        params = {
            "db":      "pubmed",
            "id":      ",".join(batch),
            "retmode": "json",
        }
        if api_key:
            params["api_key"] = api_key

        try:
            time.sleep(delay)
            resp = requests.get(base_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            result_block = data.get("result", {})
            uid_list = result_block.get("uids", batch)

            for pmid in uid_list:
                pmid_str = str(pmid)
                record = result_block.get(pmid_str)
                if record and isinstance(record, dict):
                    results[pmid_str] = _parse_esummary_record(pmid_str, record)
                else:
                    log.debug(f"No record found for PMID {pmid_str} in esummary response")

            log.debug(f"Metadata fetched for batch {i//batch_size + 1}: {len(batch)} PMIDs")

        except Exception as e:
            log.error(f"Metadata fetch failed for batch starting at {i}: {e}")

    return results


def _parse_esummary_record(pmid: str, record: dict) -> dict:
    # Authors
    authors = []
    for author in record.get("authors", []):
        if isinstance(author, dict):
            name = author.get("name", "").strip()
        else:
            name = str(author).strip()
        if name:
            authors.append(name)

    # Article types
    article_types = []
    for pt in record.get("pubtype", []):
        if isinstance(pt, dict):
            article_types.append(pt.get("value", ""))
        elif isinstance(pt, str):
            article_types.append(pt)

    # DOI and PMCID from articleids
    doi = ""
    pmcid = ""
    for id_rec in record.get("articleids", []):
        if not isinstance(id_rec, dict):
            continue
        if id_rec.get("idtype") == "doi":
            doi = id_rec.get("value", "")
        if id_rec.get("idtype") == "pmc":
            pmcid = id_rec.get("value", "")

    # Publication year
    pub_date = record.get("pubdate", "")
    pub_year = pub_date[:4] if pub_date and len(pub_date) >= 4 else ""

    return {
        "pmid":             pmid,
        "title":            record.get("title", "").strip(),
        "authors":          "; ".join(authors),
        "journal":          record.get("source", "").strip(),
        "publication_year": pub_year,
        "doi":              doi,
        "pmcid":            pmcid,
        "article_type":     "; ".join(article_types),
        "mesh_terms":       "",
        "abstract":         "",
    }


def fetch_abstract_and_mesh(pmid: str, api_cfg: dict) -> dict:
    base_url = api_cfg.get("efetch_url", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi")
    api_key  = api_cfg.get("api_key", "")
    delay    = api_cfg.get("request_delay", 0.4)

    params = {"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"}
    if api_key:
        params["api_key"] = api_key

    try:
        time.sleep(delay)
        resp = requests.get(base_url, params=params, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        return {
            "abstract":   _extract_abstract_xml(root),
            "mesh_terms": _extract_mesh_xml(root),
        }
    except Exception as e:
        log.error(f"Abstract/MeSH fetch failed for PMID {pmid}: {e}")
        return {"abstract": "", "mesh_terms": ""}


def _extract_abstract_xml(root: ET.Element) -> str:
    texts = []
    for abstract_text in root.iter("AbstractText"):
        label = abstract_text.get("Label", "")
        text  = (abstract_text.text or "").strip()
        if label:
            texts.append(f"{label}: {text}")
        elif text:
            texts.append(text)
    return " ".join(texts)


def _extract_mesh_xml(root: ET.Element) -> str:
    terms = []
    for descriptor in root.iter("DescriptorName"):
        term = (descriptor.text or "").strip()
        if term:
            terms.append(term)
    return "; ".join(terms)
