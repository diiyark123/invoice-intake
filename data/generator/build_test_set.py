"""Build the synthetic part of the held-out test set (playbook M1 step 7).

20 original invoices (incl. a few from vendors that are NOT seeded, D14) + 5 seeded duplicates:
exact copy, same number in a different file, invoice-number variant, rescanned copy, date +2 days.
Writes data/test/duplicates.json and data/test/manifest.json.

Usage: python -m data.generator.build_test_set [--out data/test] [--force]

Only eval/run_eval.py may READ data/test. Never tune anything on it.
"""

import argparse
import json
import random
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from faker import Faker

from app.seed_data import KNOWN_VENDORS, UNKNOWN_VENDORS
from data.generator.generate import Generated, write_invoice
from data.generator.layouts import LAYOUTS
from data.generator.model import make_invoice, with_changes
from data.generator.scanify import scanify

ORIGINALS = 20
UNKNOWN_VENDOR_COUNT = 3
SCAN_FRACTION = 0.35


@dataclass
class TestSet:
    originals: list[Generated]
    duplicates: list[dict[str, str]]
    manifest: list[dict[str, Any]]


def build(out_dir: Path, seed: int = 2026, today: date | None = None) -> TestSet:
    rng = random.Random(seed)
    faker = Faker("en_IN")
    faker.seed_instance(seed)
    today = today or date.today()
    layouts = list(LAYOUTS)
    unknown_at = dict(
        zip(
            sorted(rng.sample(range(ORIGINALS), UNKNOWN_VENDOR_COUNT)), UNKNOWN_VENDORS, strict=True
        )
    )

    originals: list[Generated] = []
    for i in range(ORIGINALS):
        vendors = [unknown_at[i]] if i in unknown_at else KNOWN_VENDORS
        inv = make_invoice(rng, faker, today, vendors)
        # Originals 0-3 are duplicate sources and stay clean PDFs (the rescan needs a PDF to scan).
        scan = i >= 4 and rng.random() < SCAN_FRACTION
        if i == 2:  # source for the number-variant duplicate
            n = rng.randint(10, 99)
            inv = with_changes(inv, invoice_number=f"INV-{n:04d}")
        layout = layouts[i % len(layouts)]
        originals.append(write_invoice(inv, out_dir, f"test_{i + 1:04d}", layout, scan, rng))

    dup_specs: list[dict[str, str]] = []

    def name(k: int) -> str:
        return f"test_{ORIGINALS + k:04d}"

    # 1. exact copy: identical bytes
    src = originals[0]
    dup = out_dir / f"{name(1)}{src.file.suffix}"
    shutil.copyfile(src.file, dup)
    shutil.copyfile(src.label_file, out_dir / f"{name(1)}.json")
    dup_specs.append({"file": dup.name, "duplicate_of": src.file.name, "kind": "exact_copy"})

    # 2. same invoice number, different file (re-rendered with another layout)
    src = originals[1]
    other_layout = layouts[(layouts.index(src.layout) + 2) % len(layouts)]
    g = write_invoice(src.invoice, out_dir, name(2), other_layout, False, rng)
    dup_specs.append(
        {"file": g.file.name, "duplicate_of": src.file.name, "kind": "same_number_different_file"}
    )

    # 3. invoice number printed differently: INV-0042 vs 42
    src = originals[2]
    bare = str(int(src.invoice.invoice_number.removeprefix("INV-")))
    g = write_invoice(
        with_changes(src.invoice, invoice_number=bare), out_dir, name(3), src.layout, False, rng
    )
    dup_specs.append({"file": g.file.name, "duplicate_of": src.file.name, "kind": "number_variant"})

    # 4. rescanned copy of a clean PDF
    src = originals[3]
    dup = out_dir / f"{name(4)}.jpg"
    scanify(str(src.file), str(dup), rng)
    shutil.copyfile(src.label_file, out_dir / f"{name(4)}.json")
    dup_specs.append({"file": dup.name, "duplicate_of": src.file.name, "kind": "rescanned_copy"})

    # 5. same invoice, date shifted by 2 days
    src = originals[4]
    shifted = with_changes(
        src.invoice,
        invoice_date=src.invoice.invoice_date + timedelta(days=2),
        due_date=src.invoice.due_date + timedelta(days=2) if src.invoice.due_date else None,
    )
    g = write_invoice(shifted, out_dir, name(5), src.layout, False, rng)
    dup_specs.append(
        {"file": g.file.name, "duplicate_of": src.file.name, "kind": "date_shift_2_days"}
    )

    manifest = [
        {
            "file": o.file.name,
            "label": o.label_file.name,
            "source": "synthetic",
            "layout": o.layout,
            "scanned": o.scanned,
            "vendor_seeded": o.invoice.vendor in KNOWN_VENDORS,
        }
        for o in originals
    ] + [
        {
            "file": d["file"],
            "label": Path(d["file"]).stem + ".json",
            "source": "synthetic",
            "duplicate_kind": d["kind"],
        }
        for d in dup_specs
    ]

    (out_dir / "duplicates.json").write_text(json.dumps(dup_specs, indent=2) + "\n")
    (out_dir / "manifest.json").write_text(
        json.dumps({"generated_on": today.isoformat(), "seed": seed, "files": manifest}, indent=2)
        + "\n"
    )
    return TestSet(originals, dup_specs, manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the synthetic held-out test set")
    parser.add_argument("--out", type=Path, default=Path("data/test"))
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--force", action="store_true", help="replace an existing test set")
    args = parser.parse_args()

    if args.out.exists() and any(p.name != ".gitkeep" for p in args.out.iterdir()):
        if not args.force:
            raise SystemExit(
                f"{args.out} is not empty. The test set is frozen; use --force to rebuild."
            )
        backup = Path(tempfile.mkdtemp(prefix="test_set_backup_"))
        shutil.copytree(args.out, backup, dirs_exist_ok=True)
        shutil.rmtree(args.out)
        print(f"Old test set backed up to {backup}")

    result = build(args.out, seed=args.seed)
    n_files, n_dups = len(result.manifest), len(result.duplicates)
    print(f"Wrote {n_files} files ({n_dups} seeded duplicates) to {args.out}")


if __name__ == "__main__":
    main()
