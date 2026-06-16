"""
appraise.py — Stage 5: AI critical appraisal
PT Research Pipeline
"""

import json
import logging
import os
import psutil
import requests
from typing import Optional

log = logging.getLogger(__name__)

REQUIRED_FIELDS = [
    "study_design", "oxford_level", "oxford_level_rationale",
    "mcdermott_grade", "mcdermott_grade_rationale", "clinical_context",
    "ai_tool_described", "implementation_result", "implementation_detail",
    "governance_recommendations", "patient_safety_concerns", "clinician_role",
    "outcome_measures", "population", "relevance_to_primary_question",
    "relevance_rationale", "clinician_summary", "appraisal_confidence",
    "appraisal_notes",
]

VALID_OXFORD_LEVELS    = {"1a", "1b", "1c", "2a", "2b", "2c", "3a", "3b", "4", "5"}
VALID_MCDERMOTT_GRADES = {"A", "B", "C", "D"}
VALID_RELEVANCE        = {"high", "moderate", "low"}
VALID_IMPL_RESULTS     = {"success", "failure", "mixed", "not_reported"}
VALID_CONFIDENCE       = {"high", "moderate", "low"}


def appraise_article(article: dict, model_cfg: dict, paths_cfg: dict) -> dict:
    pmid       = article["pmid"]
    full_text  = article.get("full_text_content", "").strip()
    result     = article.copy()
    result["appraisal_complete"] = False
    result["model_used"]         = ""

    if not article.get("full_text_available", False) or not full_text:
        log.info(f"PMID {pmid}: appraisal skipped — no full text (gate enforced)")
        return result

    model_name = _select_model(model_cfg)
    log.info(f"PMID {pmid}: running appraisal with {model_name}")

    prompt_path = paths_cfg.get("prompt", "prompts/appraisal_prompt.txt")
    prompt      = _build_prompt(prompt_path, article, full_text)

    if not prompt:
        log.error(f"PMID {pmid}: prompt build failed — skipping appraisal")
        return result

    raw_response = _call_ollama(prompt, model_name, model_cfg)

    if not raw_response:
        log.error(f"PMID {pmid}: Ollama returned empty response")
        return result

    parsed = _parse_response(raw_response, pmid)

    if not parsed:
        log.error(f"PMID {pmid}: response parsing failed")
        return result

    result.update({
        "appraisal_complete":    True,
        "model_used":            model_name,
        "oxford_level":          parsed.get("oxford_level", ""),
        "mcdermott_grade":       parsed.get("mcdermott_grade", ""),
        "relevance_to_pq":       parsed.get("relevance_to_primary_question", ""),
        "implementation_result": parsed.get("implementation_result", ""),
        "appraisal_confidence":  parsed.get("appraisal_confidence", ""),
        "_appraisal_data":       parsed,
    })

    log.info(
        f"PMID {pmid}: appraisal complete — "
        f"Oxford {parsed.get('oxford_level','?')} / "
        f"McDermott {parsed.get('mcdermott_grade','?')} / "
        f"Relevance {parsed.get('relevance_to_primary_question','?')}"
    )
    return result


def _select_model(model_cfg: dict) -> str:
    primary   = model_cfg.get("primary", "llama-stable:latest")
    fallback  = model_cfg.get("fallback", "llama-stable:latest")
    threshold = model_cfg.get("memory_threshold_gb", 8)
    try:
        mem          = psutil.virtual_memory()
        available_gb = mem.available / (1024 ** 3)
        if available_gb < threshold:
            log.warning(f"RAM {available_gb:.1f}GB below threshold — using fallback {fallback}")
            return fallback
        return primary
    except Exception as e:
        log.warning(f"Memory check failed ({e}) — using fallback {fallback}")
        return fallback


def _build_prompt(prompt_path: str, article: dict, full_text: str) -> Optional[str]:
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            lines    = f.readlines()
            template = "".join(line for line in lines if not line.startswith("#")).strip()

        # Use explicit string replacement instead of str.format()
        # This avoids conflicts with JSON curly braces in the prompt template
        substitutions = {
            "{title}":            str(article.get("title", "Not available")),
            "{authors}":          str(article.get("authors", "Not available")),
            "{journal}":          str(article.get("journal", "Not available")),
            "{publication_year}": str(article.get("publication_year", "Not available")),
            "{doi}":              str(article.get("doi", "Not available")),
            "{article_type}":     str(article.get("article_type", "Not available")),
            "{mesh_terms}":       str(article.get("mesh_terms", "Not available")),
            "{full_text}":        full_text[:8000] + ("\n\n[TRUNCATED]" if len(full_text) > 8000 else ""),
        }
        prompt = template
        for key, value in substitutions.items():
            prompt = prompt.replace(key, value)

        return prompt

    except FileNotFoundError:
        log.error(f"Prompt file not found: {prompt_path}")
        return None
    except Exception as e:
        log.error(f"Prompt build failed: {e}")
        return None


def _call_ollama(prompt: str, model_name: str, model_cfg: dict) -> Optional[str]:
    base_url    = model_cfg.get("base_url", "http://localhost:11434")
    max_tokens  = model_cfg.get("max_tokens", 2000)
    temperature = model_cfg.get("temperature", 0.1)
    api_url     = f"{base_url}/api/generate"

    payload = {
        "model":  model_name,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx":     10000,
        },
    }

    try:
        resp = requests.post(api_url, json=payload, timeout=600)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "").strip()
    except requests.exceptions.ConnectionError:
        log.error("Cannot connect to Ollama — ensure Ollama is running: 'ollama serve'")
        return None
    except requests.exceptions.Timeout:
        log.error(f"Ollama request timed out for model {model_name}")
        return None
    except Exception as e:
        log.error(f"Ollama API call failed: {e}")
        return None


def _parse_response(raw: str, pmid: str) -> Optional[dict]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines   = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.error(f"PMID {pmid}: JSON parse error: {e}")
        log.debug(f"Raw response (first 500 chars): {raw[:500]}")
        return None

    missing = [f for f in REQUIRED_FIELDS if f not in parsed]
    if missing:
        log.warning(f"PMID {pmid}: appraisal missing fields: {missing}")

    parsed = _normalise_field(parsed, "oxford_level",                VALID_OXFORD_LEVELS,    pmid)
    parsed = _normalise_field(parsed, "mcdermott_grade",             VALID_MCDERMOTT_GRADES, pmid)
    parsed = _normalise_field(parsed, "relevance_to_primary_question", VALID_RELEVANCE,      pmid)
    parsed = _normalise_field(parsed, "implementation_result",       VALID_IMPL_RESULTS,     pmid)
    parsed = _normalise_field(parsed, "appraisal_confidence",        VALID_CONFIDENCE,       pmid)

    summary = parsed.get("clinician_summary", "")
    words   = summary.split()
    if len(words) > 220:
        parsed["clinician_summary"] = " ".join(words[:200]) + " [truncated]"

    return parsed


def _normalise_field(parsed: dict, field: str, valid_values: set, pmid: str) -> dict:
    value = str(parsed.get(field, "")).strip()
    if value in valid_values:
        return parsed
    for valid in valid_values:
        if value.lower() == valid.lower():
            parsed[field] = valid
            return parsed
    if value:
        log.warning(f"PMID {pmid}: invalid value '{value}' for '{field}' — setting to 'unknown'")
    parsed[field] = "unknown"
    return parsed
