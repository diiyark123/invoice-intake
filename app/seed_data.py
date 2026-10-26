"""Fictional vendors for Meridian Supplies. Shared by the seed script and the invoice generator."""

from typing import TypedDict


class VendorSeed(TypedDict):
    name: str
    aliases: list[str]
    tax_id: str | None
    city: str


KNOWN_VENDORS: list[VendorSeed] = [
    {
        "name": "Apex Industrial Supplies Pvt Ltd",
        "aliases": ["Apex Industrial", "AISPL"],
        "tax_id": "27AABCA1234F1Z5",
        "city": "Mumbai",
    },
    {
        "name": "Bharat Packaging Co",
        "aliases": ["Bharat Pack"],
        "tax_id": "29AACCB2345G1Z2",
        "city": "Bengaluru",
    },
    {
        "name": "Coastal Logistics LLP",
        "aliases": ["Coastal Logistics"],
        "tax_id": "33AAJFC3456H1Z9",
        "city": "Chennai",
    },
    {
        "name": "Deccan Office Solutions",
        "aliases": ["DOS", "Deccan Office"],
        "tax_id": "36AAKFD4567J1Z1",
        "city": "Hyderabad",
    },
    {
        "name": "Evergreen Chemicals Ltd",
        "aliases": ["Evergreen Chem"],
        "tax_id": "24AACCE5678K1Z4",
        "city": "Ahmedabad",
    },
    {
        "name": "Fortune Steel Traders",
        "aliases": ["Fortune Steel"],
        "tax_id": "27AAGFF6789L1Z7",
        "city": "Pune",
    },
    {
        "name": "Ganga Electricals Pvt Ltd",
        "aliases": ["Ganga Electric"],
        "tax_id": "09AACCG7890M1Z3",
        "city": "Lucknow",
    },
    {
        "name": "Horizon IT Services",
        "aliases": ["Horizon IT"],
        "tax_id": "29AAHFH8901N1Z6",
        "city": "Bengaluru",
    },
    {
        "name": "Indus Fasteners Inc",
        "aliases": ["Indus Fasteners"],
        "tax_id": "06AACCI9012P1Z8",
        "city": "Gurugram",
    },
    {
        "name": "Jupiter Safety Equipment",
        "aliases": ["Jupiter Safety"],
        "tax_id": "19AAJFJ0123Q1Z2",
        "city": "Kolkata",
    },
    {
        "name": "Kaveri Cleaning Supplies",
        "aliases": ["Kaveri Clean"],
        "tax_id": "33AAKFK1234R1Z5",
        "city": "Coimbatore",
    },
    {
        "name": "Lotus Printing Press",
        "aliases": ["Lotus Press", "Lotus Printers"],
        "tax_id": "07AALFL2345S1Z9",
        "city": "New Delhi",
    },
    {
        "name": "Meghna Food Services",
        "aliases": ["Meghna Foods"],
        "tax_id": "32AAMFM3456T1Z1",
        "city": "Kochi",
    },
    {
        "name": "Nova Tools & Hardware",
        "aliases": ["Nova Tools", "Nova Hardware"],
        "tax_id": "27AANFN4567U1Z4",
        "city": "Nashik",
    },
    {
        "name": "Orbit Courier Services Pvt Ltd",
        "aliases": ["Orbit Courier"],
        "tax_id": "29AACCO5678V1Z7",
        "city": "Mysuru",
    },
]

# Deliberately NOT seeded: used in the test set to exercise the vendor_known rule (D14).
UNKNOWN_VENDORS: list[VendorSeed] = [
    {"name": "Pinnacle Uniforms", "aliases": [], "tax_id": "24AAPFP6789W1Z2", "city": "Surat"},
    {
        "name": "Quartz Lab Instruments",
        "aliases": [],
        "tax_id": "36AAQFQ7890X1Z5",
        "city": "Hyderabad",
    },
    {
        "name": "Riverstone Furniture Co",
        "aliases": [],
        "tax_id": "08AARFR8901Y1Z8",
        "city": "Jaipur",
    },
]
