"""Run the full pipeline on a labelled dataset and save the metrics (spec §13 M3/M5, D13).

Usage:
    python -m eval.run_eval --note "baseline"                  # held-out test set
    python -m eval.run_eval --dataset dev --prompt extract_v2  # development set, for tuning

- Uses a separate database (`invoice_eval`), wiped, migrated and seeded on every run.
- Files are processed in a fixed order (originals before their seeded duplicates).
- Calls the REAL LLM provider configured in .env, so it costs a little money.
- This is the ONLY code allowed to read data/test. Tune on --dataset dev only.
"""

import argparse
import hashlib
import json
import logging
import tempfile
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.config import get_settings
from app.models import Document, ExtractedField
from app.pipeline.extract import PROMPT_VERSION
from app.pipeline.ingest import MIME_TYPES, detect_type
from app.pipeline.llm.factory import get_provider
from app.pipeline.orchestrator import PipelineDeps, process_document
from app.seed import seed
from app.services.assessment import latest_extraction, load_settings
from app.storage import LocalStorage
from eval.metrics import DocResult, compare_document, summarize, threshold_sweep

ROOT = Path(__file__).resolve().parents[1]
DATASETS = {"test": ROOT / "data" / "test", "dev": ROOT / "data" / "dev"}
RESULTS_DIRS = {"test": ROOT / "eval" / "results", "dev": ROOT / "eval" / "results" / "dev"}
EVAL_DB = "invoice_eval"
SUMMARY_KEYS = (
    "field_accuracy_overall",
    "field_accuracy_header",
    "auto_approval_rate",
    "wrong_field_rate_in_auto_approved",
    "duplicates_caught",
    "false_duplicate_flags",
    "failed",
    "avg_processing_seconds",
    "cost_per_invoice_usd",
    "projected_monthly_cost_usd",
)

logger = logging.getLogger("eval")


def reset_eval_database(base_url: str) -> str:
    url = make_url(base_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{EVAL_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{EVAL_DB}"'))
    admin.dispose()
    eval_url = url.set(database=EVAL_DB).render_as_string(hide_password=False)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", eval_url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    return eval_url


def _json_or(path: Path, default: Any) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def dataset_files(data_dir: Path, duplicates: list[dict[str, str]]) -> list[Path]:
    """Every invoice file that has a label, originals before duplicates (sorted names)."""
    files = [
        p
        for p in sorted(data_dir.iterdir())
        if p.suffix.lower() in (".pdf", ".jpg", ".jpeg", ".png")
        and (data_dir / f"{p.stem}.json").exists()
    ]
    dups = {d["file"] for d in duplicates}
    return [f for f in files if f.name not in dups] + [f for f in files if f.name in dups]


def collect(sf: sessionmaker, doc_id: uuid.UUID, file: Path) -> DocResult:
    label = json.loads((file.parent / f"{file.stem}.json").read_text())
    with sf() as s:
        doc = s.get(Document, doc_id)
        assert doc is not None
        ex = latest_extraction(s, doc_id)
        header: dict[str, Any] = {}
        lines: dict[int, dict[str, Any]] = {}
        if ex is not None:
            for f in s.scalars(select(ExtractedField).where(ExtractedField.extraction_id == ex.id)):
                if f.line_item_index is None:
                    header[f.field_name] = f.value_text
                else:
                    lines.setdefault(f.line_item_index, {})[f.field_name] = f.value_text
        return DocResult(
            file=file.name,
            status=doc.status,
            review_reasons=list(doc.review_reasons or []),
            processing_ms=doc.processing_ms,
            cost_usd=ex.cost_usd if ex else None,
            outcomes=compare_document(header, [lines[i] for i in sorted(lines)], label),
            error=doc.error_message,
            overall_confidence=ex.overall_confidence if ex else None,
        )


def run(dataset: str, prompt_version: str, note: str) -> Path:
    data_dir = DATASETS[dataset]
    settings = get_settings()
    eval_url = reset_eval_database(settings.database_url)
    engine = create_engine(eval_url)
    sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sf() as s:
        seed(s)
        threshold = load_settings(s).confidence_threshold

    provider = get_provider(settings)
    today = date.today()
    duplicates = _json_or(data_dir / "duplicates.json", [])
    manifest = _json_or(data_dir / "manifest.json", {})
    files = dataset_files(data_dir, duplicates)

    results: list[DocResult] = []
    with tempfile.TemporaryDirectory(prefix="eval_storage_") as tmp:
        storage = LocalStorage(tmp)
        deps = PipelineDeps(
            sf, storage, lambda: provider, settings.tesseract_cmd, lambda: today, prompt_version
        )
        for n, file in enumerate(files, 1):
            data = file.read_bytes()
            doc_id = uuid.uuid4()
            key = f"{doc_id}/original/{file.name}"
            storage.save(data, key)
            with sf() as s:
                s.add(
                    Document(
                        id=doc_id,
                        filename=file.name,
                        storage_key=key,
                        mime_type=MIME_TYPES[detect_type(data)],
                        sha256=hashlib.sha256(data).hexdigest(),
                    )
                )
                s.commit()
            started = time.perf_counter()
            process_document(doc_id, deps)
            result = collect(sf, doc_id, file)
            results.append(result)
            ok = sum(o.correct for o in result.outcomes)
            print(
                f"[{n:2}/{len(files)}] {file.name:18} {result.status:13} "
                f"fields {ok}/{len(result.outcomes)}  {time.perf_counter() - started:5.1f}s  "
                f"{','.join(result.review_reasons)}"
            )
    engine.dispose()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = {
        "run_at": stamp,
        "note": note,
        "dataset": dataset,
        "config": {
            "provider": settings.llm_provider,
            "model": provider.model,
            "prompt_version": prompt_version,
            "confidence_threshold": threshold,
            "today": today.isoformat(),
        },
        "data": {
            "files": len(files),
            "seeded_duplicates": len(duplicates),
            "composition": "synthetic only (public-dataset and phone-photo samples not added yet)",
            "generated_on": manifest.get("generated_on"),
        },
        "metrics": summarize(results, duplicates),
        "threshold_sweep": threshold_sweep(results),
        "documents": [
            {
                "file": r.file,
                "status": r.status,
                "review_reasons": r.review_reasons,
                "overall_confidence": r.overall_confidence,
                "processing_ms": r.processing_ms,
                "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None,
                "error": r.error,
                "wrong_fields": [
                    {"field": o.field, "line": o.line_index, "expected": o.expected, "got": o.got}
                    for o in r.outcomes
                    if not o.correct
                ],
            }
            for r in results
        ],
    }
    out_dir = RESULTS_DIRS[dataset]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}.json"
    path.write_text(json.dumps(output, indent=2, default=str) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the pipeline on a labelled dataset")
    parser.add_argument("--dataset", choices=list(DATASETS), default="test")
    parser.add_argument("--prompt", default=PROMPT_VERSION, help="prompt version, e.g. extract_v2")
    parser.add_argument("--note", default="", help="free text saved with the results")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    path = run(args.dataset, args.prompt, args.note)
    result = json.loads(path.read_text())
    print(f"\nSaved {path.relative_to(ROOT)}")
    for key in SUMMARY_KEYS:
        print(f"  {key:36} {result['metrics'][key]}")
    print("\n  threshold  auto-approved  wrong-field rate")
    for row in result["threshold_sweep"]:
        print(
            f"  {row['threshold']:9.2f}  {row['auto_approval_rate']:13}  "
            f"{row['wrong_field_rate_in_auto_approved']}"
        )


if __name__ == "__main__":
    main()
