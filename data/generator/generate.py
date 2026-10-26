"""Generate synthetic invoices with matching label JSON files.

Usage:
    python -m data.generator.generate --count 20 --out data/dev
    python -m data.generator.generate --count 20 --out data/dev --scan 0.4 --seed 7
    python -m data.generator.generate --count 60 --out data/dev --scan 0.5 --unknown 0.1

Each invoice produces <name>.pdf (or <name>.jpg when scanned) and <name>.json (the label).
"""

import argparse
import json
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from faker import Faker

from app.seed_data import UNKNOWN_VENDORS
from data.generator.layouts import LAYOUTS
from data.generator.model import InvoiceData, make_invoice
from data.generator.scanify import scanify


@dataclass
class Generated:
    name: str
    file: Path
    label_file: Path
    layout: str
    scanned: bool
    invoice: InvoiceData


def write_invoice(
    inv: InvoiceData,
    out_dir: Path,
    name: str,
    layout: str,
    scan: bool,
    rng: random.Random,
) -> Generated:
    """Render one invoice to disk (PDF, or JPEG if scan=True) plus its label."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{name}.pdf"
    LAYOUTS[layout](str(pdf_path), inv)
    file = pdf_path
    if scan:
        file = out_dir / f"{name}.jpg"
        scanify(str(pdf_path), str(file), rng)
        pdf_path.unlink()
    label_file = out_dir / f"{name}.json"
    label_file.write_text(json.dumps(inv.label(), indent=2) + "\n")
    return Generated(name, file, label_file, layout, scan, inv)


def generate(
    count: int,
    out_dir: Path,
    seed: int = 42,
    scan_fraction: float = 0.0,
    today: date | None = None,
    prefix: str = "invoice",
    unknown_fraction: float = 0.0,
) -> list[Generated]:
    rng = random.Random(seed)
    faker = Faker("en_IN")
    faker.seed_instance(seed)
    today = today or date.today()
    layouts = list(LAYOUTS)

    results = []
    for i in range(1, count + 1):
        vendors = UNKNOWN_VENDORS if rng.random() < unknown_fraction else None
        inv = make_invoice(rng, faker, today, vendors)
        layout = layouts[(i - 1) % len(layouts)]  # round-robin so every layout appears
        scan = rng.random() < scan_fraction
        results.append(write_invoice(inv, out_dir, f"{prefix}_{i:04d}", layout, scan, rng))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic invoices + labels")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--out", type=Path, default=Path("data/dev"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--scan",
        type=float,
        default=0.0,
        help="fraction of invoices (0-1) rendered as noisy scanned JPEGs",
    )
    parser.add_argument(
        "--unknown",
        type=float,
        default=0.0,
        help="fraction of invoices (0-1) from vendors that are not in the seed data",
    )
    args = parser.parse_args()

    results = generate(
        args.count, args.out, seed=args.seed, scan_fraction=args.scan, unknown_fraction=args.unknown
    )
    scanned = sum(r.scanned for r in results)
    print(f"Wrote {len(results)} invoices ({scanned} scanned) + labels to {args.out}")


if __name__ == "__main__":
    main()
