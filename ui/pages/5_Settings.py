"""Manager settings: approval threshold, rule tolerances, vendor list. Every change is audited."""

from decimal import Decimal

import pandas as pd
import streamlit as st
from api_client import ApiError
from common import client, require_login

require_login(role="manager")
st.title("Settings")
api = client()

try:
    current = api.get_settings()
    vendors = api.vendors()
except ApiError as exc:
    st.error(exc.message)
    st.stop()

st.subheader("Automatic approval")
with st.form("settings"):
    threshold = st.slider(
        "Approve automatically when every value is at least this sure",
        min_value=0.50,
        max_value=1.00,
        value=float(current["confidence_threshold"]),
        step=0.01,
        help="Higher = fewer automatic approvals but fewer mistakes. Check the evaluation "
        "report's threshold table before changing it.",
    )
    new_vendor_review = st.toggle(
        "Always send invoices from new vendors to review",
        value=current["require_review_for_new_vendor"],
        help="If off, a new vendor is added to the list automatically when its invoice "
        "is approved.",
    )
    tolerance = st.number_input(
        "Rounding tolerance for totals (₹)",
        min_value=0.0,
        max_value=100.0,
        value=float(current["amount_tolerance"]),
        step=0.01,
        format="%.2f",
    )
    due_days = st.number_input(
        "Latest allowed due date (days after invoice date)",
        min_value=1,
        max_value=3650,
        value=int(current["max_due_days"]),
    )
    if st.form_submit_button("Save settings", type="primary"):
        try:
            api.update_settings(
                confidence_threshold=round(threshold, 2),
                require_review_for_new_vendor=new_vendor_review,
                amount_tolerance=str(Decimal(str(tolerance)).quantize(Decimal("0.01"))),
                max_due_days=int(due_days),
            )
            st.success("Settings saved.")
        except ApiError as exc:
            st.error(exc.message)

st.subheader("Vendors")
st.caption("Aliases are other names the vendor uses on invoices, separated by commas.")
original = pd.DataFrame(
    [
        {
            "id": v["id"],
            "name": v["name"],
            "aliases": ", ".join(v["aliases"]),
            "tax_id": v["tax_id"] or "",
            "is_active": v["is_active"],
        }
        for v in vendors
    ],
    columns=["id", "name", "aliases", "tax_id", "is_active"],
)
edited = st.data_editor(
    original,
    num_rows="dynamic",
    hide_index=True,
    width="stretch",
    column_config={
        "id": None,
        "name": st.column_config.TextColumn("Name", required=True),
        "aliases": st.column_config.TextColumn("Aliases"),
        "tax_id": st.column_config.TextColumn("GSTIN"),
        "is_active": st.column_config.CheckboxColumn("Active", default=True),
    },
    key="vendors",
)


def as_payload(row: pd.Series) -> dict:
    return {
        "name": str(row["name"]).strip(),
        "aliases": [a.strip() for a in str(row["aliases"] or "").split(",") if a.strip()],
        "tax_id": str(row["tax_id"] or "").strip() or None,
        "is_active": bool(row["is_active"]) if not pd.isna(row["is_active"]) else True,
    }


if st.button("Save vendor changes"):
    before = {r["id"]: as_payload(r) for _, r in original.iterrows()}
    saved, errors = 0, []
    for _, row in edited.iterrows():
        if not str(row.get("name") or "").strip():
            continue
        payload = as_payload(row)
        vid = row.get("id")
        try:
            if vid is None or pd.isna(vid):
                api.create_vendor(payload)
                saved += 1
            elif before.get(vid) != payload:
                api.update_vendor(vid, payload)
                saved += 1
        except ApiError as exc:
            errors.append(f"{payload['name']}: {exc.message}")
    for e in errors:
        st.error(e)
    if saved:
        st.success(f"Saved {saved} vendor change(s).")
    elif not errors:
        st.info("No changes to save.")
st.caption("To stop using a vendor, untick Active. Vendors are never deleted, to keep history.")
