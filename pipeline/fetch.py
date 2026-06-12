"""
fetch.py — Stage 4: Full-text fetch
PT Research Pipeline

Uses NCBI efetch API (db=pmc) as primary method — official programmatic
access, no bot detection, returns clean JATS XML.
No FTP, no HTML scraping.
"""

import requests
import logging
import time
import os
import xml.etree.ElementTree as ET
from typing import Optional

log = logging.getLogger(__name__)

EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
IDCONV_URL  = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
OA_URL      = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
MIN_CHARS   = 2000


def fetch_full_text(article: dict, paths_cfg: dict, api_cfg: dict) -> dict:
    """
    Fetch full text for a single article via NCBI efetch API.
    Only runs if article is confirmed in PMC Open Access subset.
    """
    pmid         = article["pmid"]
    pmcid        = article.get("pmcid", "")
    articles_dir = paths_cfg.get("articles", "articles/")
    delay        = api_cfg.get("request_delay", 0.4)
    api_key      = api_cfg.get("api_key", "")

    result = article.copy()
    result["full_text_available"] = False
    result["reprocess_pending"]   = True
    result["fetch_error"]         = ""
    result["pdf_path"]            = ""
    result["full_text_content"]   = ""

    # Resolve PMCID if not already known
    if not pmcid:
        pmcid = _resolve_pmcid(pmid, delay, api_key)
        if pmcid:
            result["pmcid"] = pmcid

    if not pmcid:
        result["fetch_error"] = "No PMCID — article not in PMC"
        log.info(f"PMID {pmid}: no PMCID, skipping")
        return result

    # Confirm OA availability
    if not _confirm_oa(pmcid, delay):
        result["fetch_error"] = f"{pmcid} not in PMC Open Access subset"
        log.info(f"PMID {pmid} / {pmcid}: not OA")
        return result

    # Fetch full text XML via efetch
    os.makedirs(articles_dir, exist_ok=True)
    pmc_id_num = pmcid.replace("PMC", "")

    params = {
        "db":      "pmc",
        "id":      pmc_id_num,
        "rettype": "full",
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key

    try:
        time.sleep(delay)
        resp = requests.get(EFETCH_URL, params=params, timeout=60)
        resp.raise_for_status()

        xml_bytes = resp.content

        # Save raw XML
        xml_path = os.path.join(articles_dir, f"{pmid}.xml")
        with open(xml_path, "wb") as f:
            f.write(xml_bytes)

        # Extract readable text
        text = _extract_text_from_jats(xml_bytes)

        if not text or len(text) < MIN_CHARS:
            result["fetch_error"] = f"XML fetched but text extraction too short ({len(text)} chars)"
            log.warning(f"PMID {pmid}: XML received but extraction yielded only {len(text)} chars")
            return result

        result["full_text_available"] = True
        result["reprocess_pending"]   = False
        result["full_text_content"]   = text
        result["pdf_path"]            = xml_path
        log.info(f"PMID {pmid}: full text acquired via efetch XML ({len(text)} chars)")
        return result

    except requests.exceptions.HTTPError as e:
        result["fetch_error"] = f"efetch HTTP error: {e.response.status_code}"
        log.warning(f"PMID {pmid}: efetch returned {e.response.status_code}")
    except Exception as e:
        result["fetch_error"] = f"efetch failed: {e}"
        log.error(f"PMID {pmid}: efetch failed: {e}")

    return result


def _extract_text_from_jats(xml_bytes: bytes) -> str:
    """
    Parse JATS XML (PMC full text format) and extract clean readable text.
    Targets: title, abstract, body sections, conclusions.
    """
    try:
        root = ET.fromstring(xml_bytes)
        parts = []

        # Title
        for t in root.iter("article-title"):
            if t.text:
                parts.append(f"TITLE: {''.join(t.itertext()).strip()}")
                break

        # Abstract
        for abstract in root.iter("abstract"):
            abstract_text = []
            for child in abstract.iter():
                if child.tag == "title" and child.text:
                    abstract_text.append(f"\n{child.text.strip().upper()}:")
                elif child.tag == "p":
                    p_text = "".join(child.itertext()).strip()
                    if p_text:
                        abstract_text.append(p_text)
            if abstract_text:
                parts.append("ABSTRACT:\n" + " ".join(abstract_text))
            break  # Only first abstract

        # Body
        for body in root.iter("body"):
            body_parts = []
            for sec in body.iter("sec"):
                title_el = sec.find("title")
                if title_el is not None:
                    sec_title = "".join(title_el.itertext()).strip()
                    if sec_title:
                        body_parts.append(f"\n{sec_title.upper()}:")
                for p in sec.findall("p"):
                    p_text = "".join(p.itertext()).strip()
                    if p_text:
                        body_parts.append(p_text)
            if body_parts:
                parts.append("BODY:\n" + " ".join(body_parts))
            break  # Only first body

        text = "\n\n".join(parts)

        # Truncate to ~80,000 chars
        if len(text) > 80000:
            text = text[:80000] + "\n\n[TRUNCATED]"

        return text

    except ET.ParseError as e:
        log.debug(f"JATS XML parse error: {e}")
        return ""
    except Exception as e:
        log.debug(f"JATS text extraction failed: {e}")
        return ""


def _resolve_pmcid(pmid: str, delay: float, api_key: str = "") -> Optional[str]:
    """Resolve PMID to PMCID via NCBI ID converter."""
    try:
        params = {"ids": pmid, "format": "json"}
        if api_key:
            params["api_key"] = api_key
        time.sleep(delay)
        resp = requests.get(IDCONV_URL, params=params, timeout=20)
        resp.raise_for_status()
        records = resp.json().get("records", [])
        if records:
            pmcid = records[0].get("pmcid", "")
            if pmcid and pmcid.startswith("PMC"):
                return pmcid
    except Exception as e:
        log.debug(f"PMCID resolution failed for PMID {pmid}: {e}")
    return None


def _confirm_oa(pmcid: str, delay: float) -> bool:
    """Confirm article is in PMC Open Access subset."""
    try:
        time.sleep(delay)
        resp = requests.get(OA_URL, params={"id": pmcid}, timeout=20)
        resp.raise_for_status()
        root  = ET.fromstring(resp.content)
        error = root.find(".//error")
        if error is not None:
            return False
        # Any link element means it's OA
        return root.find(".//link") is not None
    except Exception as e:
        log.debug(f"OA confirm failed for {pmcid}: {e}")
        return False
