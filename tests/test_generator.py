import json
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

from faker import Faker

from data.generator.build_test_set import build
from data.generator.generate import generate
from data.generator.layouts import LAYOUTS, indian
from data.generator.model import make_invoice

TODAY = date(2026, 10, 26)
LABEL_KEYS = {
    "doc_class",
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "tax",
    "total",
    "line_items",
}
LINE_KEYS = {"description", "quantity", "unit_price", "amount"}


def check_label(label: dict) -> None:
    assert set(label) == LABEL_KEYS
    assert label["doc_class"] == "invoice"
    assert label["line_items"], "every invoice has at least one line"
    for li in label["line_items"]:
        assert set(li) == LINE_KEYS
        exact = Decimal(li["quantity"]) * Decimal(li["unit_price"])
        assert abs(exact - Decimal(li["amount"])) <= Decimal("0.005")
    for key in ("subtotal", "tax", "total"):
        assert len(label[key].split(".")[1]) == 2, "amounts are strings with 2 decimals"
    subtotal = sum(Decimal(li["amount"]) for li in label["line_items"])
    assert subtotal == Decimal(label["subtotal"])
    assert Decimal(label["subtotal"]) + Decimal(label["tax"]) == Decimal(label["total"])
    inv_date = date.fromisoformat(label["invoice_date"])
    assert inv_date < TODAY
    assert (TODAY - inv_date).days <= 366
    if label["due_date"]:
        assert date.fromisoformat(label["due_date"]) >= inv_date


def test_random_invoices_are_consistent() -> None:
    rng = random.Random(1)
    faker = Faker("en_IN")
    faker.seed_instance(1)
    for _ in range(200):
        check_label(make_invoice(rng, faker, TODAY).label())


def test_generate_writes_files_and_valid_labels(tmp_path: Path) -> None:
    results = generate(10, tmp_path, seed=3, scan_fraction=0.3, today=TODAY)
    assert len(results) == 10
    assert {r.layout for r in results} == set(LAYOUTS), "all 5 layouts are used"
    for r in results:
        assert r.file.exists() and r.file.stat().st_size > 1000
        assert r.file.suffix == (".jpg" if r.scanned else ".pdf")
        check_label(json.loads(r.label_file.read_text()))
    assert len(list(tmp_path.glob("*.json"))) == 10


def test_generate_is_deterministic_with_seed(tmp_path: Path) -> None:
    a = generate(5, tmp_path / "a", seed=9, scan_fraction=0.5, today=TODAY)
    b = generate(5, tmp_path / "b", seed=9, scan_fraction=0.5, today=TODAY)
    for x, y in zip(a, b, strict=True):
        assert x.label_file.read_text() == y.label_file.read_text()
        assert x.file.read_bytes() == y.file.read_bytes()


def test_different_seeds_give_different_invoices(tmp_path: Path) -> None:
    a = generate(3, tmp_path / "a", seed=1, today=TODAY)
    b = generate(3, tmp_path / "b", seed=2, today=TODAY)
    assert [r.label_file.read_text() for r in a] != [r.label_file.read_text() for r in b]


def test_indian_grouping() -> None:
    assert indian(Decimal("123456.00")) == "1,23,456.00"
    assert indian(Decimal("1234567.5")) == "12,34,567.50"
    assert indian(Decimal("999.99")) == "999.99"


def test_test_set_has_five_seeded_duplicates(tmp_path: Path) -> None:
    ts = build(tmp_path, seed=5, today=TODAY)
    dups = json.loads((tmp_path / "duplicates.json").read_text())
    assert len(dups) == 5
    assert {d["kind"] for d in dups} == {
        "exact_copy",
        "same_number_different_file",
        "number_variant",
        "rescanned_copy",
        "date_shift_2_days",
    }
    for d in dups:
        assert (tmp_path / d["file"]).exists()
        assert (tmp_path / d["duplicate_of"]).exists()
        check_label(json.loads((tmp_path / (Path(d["file"]).stem + ".json")).read_text()))

    by_kind = {d["kind"]: d for d in dups}
    exact = by_kind["exact_copy"]
    assert (tmp_path / exact["file"]).read_bytes() == (
        tmp_path / exact["duplicate_of"]
    ).read_bytes()

    variant = by_kind["number_variant"]
    orig = json.loads((tmp_path / (Path(variant["duplicate_of"]).stem + ".json")).read_text())
    copy = json.loads((tmp_path / (Path(variant["file"]).stem + ".json")).read_text())
    assert orig["invoice_number"].startswith("INV-")
    assert orig["invoice_number"] != copy["invoice_number"]
    assert int(orig["invoice_number"].removeprefix("INV-")) == int(copy["invoice_number"])

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert len(manifest["files"]) == 25
    assert sum(not f["vendor_seeded"] for f in manifest["files"] if "vendor_seeded" in f) == 3
    assert len(ts.originals) == 20
