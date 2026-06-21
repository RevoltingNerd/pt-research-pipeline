"""
run_all.py — Full pipeline orchestrator
PT Research Pipeline v2

Single entry point. Runs all layers sequentially with checkpointing.
Resumes from last completed step if interrupted.

Usage:
    python3 run_all.py                    # full run
    python3 run_all.py --from-step 2     # resume from Layer 2
    python3 run_all.py --skip-layer3     # stop after Layer 2
"""

import os, sys, yaml, json, logging, argparse, subprocess
from pathlib import Path
from datetime import datetime

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))
os.chdir(PIPELINE_ROOT)

LOG_PATH = Path(f"logs/run_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
LOG_PATH.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH)]
)
log = logging.getLogger(__name__)

CHECKPOINT_FILE = Path(".pipeline_checkpoint.json")

def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"last_completed_step": 0, "run_id": datetime.now().isoformat()}

def save_checkpoint(step, data=None):
    cp = load_checkpoint()
    cp["last_completed_step"] = step
    cp["updated"] = datetime.now().isoformat()
    if data: cp.update(data)
    CHECKPOINT_FILE.write_text(json.dumps(cp, indent=2))

def run_step(name, script, args=""):
    log.info(f"\n{'='*60}")
    log.info(f"STEP: {name}")
    log.info(f"{'='*60}")
    cmd = f"python3 {script} {args}".strip()
    result = subprocess.run(cmd, shell=True, cwd=PIPELINE_ROOT)
    if result.returncode != 0:
        log.error(f"STEP FAILED: {name} (exit code {result.returncode})")
        log.error("Pipeline halted. Fix the error and rerun with --from-step to resume.")
        sys.exit(result.returncode)
    log.info(f"STEP COMPLETE: {name}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-step", type=int, default=0)
    parser.add_argument("--skip-layer3", action="store_true")
    parser.add_argument("--skip-excel", action="store_true")
    parser.add_argument("--no-clinical-impact", action="store_true",
                        help="Skip Stage 5b clinical impact extraction even if enabled in config")
    parser.add_argument("--no-archive", action="store_true",
                        help="Skip the final archive/reset step")
    parser.add_argument("--reset", action="store_true",
                        help="Clear checkpoint and start fresh")
    args = parser.parse_args()

    if not Path("config.yaml").exists():
        log.error("config.yaml not found. Copy config.yaml.example and fill in your values.")
        sys.exit(1)

    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    if args.reset and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        log.info("Checkpoint cleared — starting fresh")

    cp = load_checkpoint()
    start_from = args.from_step or cp.get("last_completed_step", 0)

    log.info(f"PT Research Pipeline v2")
    log.info(f"Research question: {cfg.get('research_question','')[:80]}...")
    log.info(f"Starting from step: {start_from + 1}")

    # Determine if clinical impact is configured and enabled
    ci_enabled = (
        cfg.get("clinical_impact", {}).get("enabled", False)
        and not args.no_clinical_impact
        and Path("run_clinical_impact.py").exists()
        and Path("run_impact_report.py").exists()
    )

    steps = [
        (1,  "Ingest — fetch feeds and build ledger",           "run_ingest.py",          "--all"),
        (2,  "Layer 0 — fast metadata extraction",              "run_layer0.py",          "--all"),
        (3,  "Layer 2 — deep 7-stage appraisal",               "run_layer2.py",          ""),
        (4,  "Backfill — fetch authors/journal/year",           "run_backfill.py",        ""),
        (5,  "Layer 3 — dynamic cluster discovery",             "run_layer3_cluster.py",  ""),
        (6,  "Layer 3 — GRADE synthesis per cluster",           "run_layer3_grade.py",    ""),
        (7,  "Export — build Excel workbook",                   "run_export.py",          ""),
        (8,  "Report — generate summary report",                "run_report.py",          ""),
        (9,  "Stage 5b — clinical impact extraction",           "run_clinical_impact.py", ""),
        (10, "Stage 5b — clinical impact synthesis report",     "run_impact_report.py",   ""),
        (11, "Archive — move outputs to archive/ and reset",    "run_archive.py",         ""),
    ]

    if args.skip_layer3:
        steps = [s for s in steps if s[0] not in (5, 6)]
    if args.skip_excel:
        steps = [s for s in steps if s[0] not in (7, 8)]
    if not ci_enabled:
        steps = [s for s in steps if s[0] not in (9, 10)]
        if not ci_enabled and not args.no_clinical_impact:
            log.info("Stage 5b skipped — set clinical_impact.enabled: true in config.yaml to enable")
    if args.no_archive:
        steps = [s for s in steps if s[0] != 11]

    # Split archive step so completion summary prints before it runs
    archive_step = next((s for s in steps if s[0] == 11), None)
    core_steps   = [s for s in steps if s[0] != 11]

    for step_num, name, script, step_args in core_steps:
        if step_num <= start_from:
            log.info(f"Skipping step {step_num} (already completed): {name}")
            continue
        if not Path(script).exists():
            log.error(f"Script not found: {script}")
            sys.exit(1)
        run_step(name, script, step_args)
        save_checkpoint(step_num)

    log.info("\n" + "="*60)
    log.info("PIPELINE COMPLETE")
    log.info("="*60)
    log.info(f"Log: {LOG_PATH}")
    topic_name = cfg.get("topic", {}).get("short_name", "research")
    safe_topic = topic_name.replace(" ", "_").lower()
    log.info("Outputs:")
    log.info(f"  ledger.csv                                — master ingest ledger")
    log.info(f"  layer0_ledger.csv                         — all screened articles")
    log.info(f"  summaries/deep/                           — Layer 2 per-article appraisals")
    log.info(f"  summaries/layer3/                         — GRADE synthesis per cluster")
    log.info(f"  {safe_topic}_evidence_base_*.xlsx          — Excel workbook for SharePoint")
    log.info(f"  {safe_topic}_synthesis_report_*.md         — markdown synthesis report")
    if ci_enabled:
        log.info(f"  clinical_impact_ledger.csv               — Stage 5b outcome extraction")
        log.info(f"  {safe_topic}_clinical_impact_report_*.md  — clinical leverage report")

    if archive_step:
        step_num, name, script, step_args = archive_step
        if step_num <= start_from:
            log.info(f"Skipping step {step_num} (already completed): {name}")
        elif not Path(script).exists():
            log.error(f"Script not found: {script}")
        else:
            run_step(name, script, step_args)
            save_checkpoint(step_num)
    else:
        log.info("\n(Archive step skipped — use run_archive.py to archive manually)")

    CHECKPOINT_FILE.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
