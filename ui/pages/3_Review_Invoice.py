"""Check one invoice: page image with boxes on the left, editable values on the right."""

import io
from typing import Any

import pandas as pd
import streamlit as st
from api_client import ApiError
from common import (
    FIELD_LABELS,
    client,
    confidence_badge,
    reason_text,
    require_login,
    status_badge,
)
from PIL import Image, ImageDraw

require_login()

LINE_COLUMNS = ["description", "quantity", "unit_price", "amount"]
BOX_COLOR = (230, 145, 0)
SELECTED_COLOR = (20, 90, 220)


def draw_boxes(
    image_bytes: bytes, fields: list[dict], page: int, selected: str | None
) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for f in fields:
        if f["page_number"] != page or not f["bbox"]:
            continue
        b = f["bbox"]
        box = (b["x0"] - 4, b["y0"] - 4, b["x1"] + 4, b["y1"] + 4)
        if key_of(f) == selected:
            draw.rectangle(box, outline=SELECTED_COLOR, width=6)
        else:
            draw.rectangle(box, outline=BOX_COLOR, width=2)
    return img


def key_of(f: dict) -> str:
    i = f["line_item_index"]
    return f["field_name"] if i is None else f"line_items.{i}.{f['field_name']}"


def label_of(key: str) -> str:
    if key.startswith("line_items."):
        _, i, name = key.split(".")
        return f"Line {int(i) + 1} – {name.replace('_', ' ')}"
    return FIELD_LABELS.get(key, key)


def blank(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None


# ---------- load ----------

doc_id = st.session_state.get("review_doc_id") or st.query_params.get("doc")
if not doc_id:
    st.info("Open an invoice from the review queue or the upload page.")
    st.stop()

api = client()
try:
    doc = api.get_document(doc_id)
except ApiError as exc:
    st.error(exc.message)
    st.stop()

ex = doc.get("extraction")
threshold = doc.get("confidence_threshold") or 0.85
editable = doc["status"] == "needs_review"
fields: list[dict] = ex["fields"] if ex else []
header = {f["field_name"]: f for f in fields if f["line_item_index"] is None}
line_indexes = sorted({f["line_item_index"] for f in fields if f["line_item_index"] is not None})
by_key = {key_of(f): f for f in fields}
failed = [r for r in (ex or {}).get("validation_results") or [] if not r["passed"]]
messages_by_field: dict[str, list[str]] = {}
for r in failed:
    for name in r["fields"]:
        messages_by_field.setdefault(name, []).append(r["message"])

title = (header.get("vendor_name") or {}).get("value_text") or doc["filename"]
st.title(title)
st.markdown(f"{status_badge(doc['status'])} &nbsp; `{doc['filename']}`")
if doc["review_reasons"]:
    st.warning(
        "**Why this needs a look:**\n"
        + "\n".join(f"- {reason_text(r)}" for r in doc["review_reasons"])
    )
if not editable:
    st.info("This invoice is no longer in review, so it can't be changed.")
if ex is None:
    st.error(doc.get("error_message") or "Nothing was extracted from this document.")
    st.stop()

left, right = st.columns([1.15, 1], gap="large")

# ---------- left: page image ----------

with left:
    pages = list(range(1, (doc.get("page_count") or 1) + 1))
    page = st.selectbox("Page", pages, disabled=len(pages) == 1) if len(pages) > 1 else 1
    on_page = [k for k, f in by_key.items() if f["page_number"] == page and f["bbox"]]
    selected = st.selectbox(
        "Highlight a value on the page",
        [None, *on_page],
        format_func=lambda k: "—" if k is None else label_of(k),
    )
    try:
        image = draw_boxes(api.page_image(doc_id, page), fields, page, selected)
        st.image(image, width="stretch")
    except ApiError as exc:
        st.error(f"Page image not available: {exc.message}")

# ---------- right: values ----------

with right:
    st.subheader("Invoice details")
    with st.form("values"):
        header_inputs: dict[str, str] = {}
        for name, label in FIELD_LABELS.items():
            f = header.get(name, {})
            badge = confidence_badge(f.get("confidence"), threshold) if f else ""
            header_inputs[name] = st.text_input(
                f"{label} {badge}",
                value=f.get("value_text") or "",
                disabled=not editable,
                key=f"h-{name}",
            )
            for msg in messages_by_field.get(name, []):
                st.caption(f"⚠️ {msg}")

        st.markdown("**Line items**")
        rows = [
            {
                "_idx": i,
                **{
                    c: (by_key.get(f"line_items.{i}.{c}") or {}).get("value_text")
                    for c in LINE_COLUMNS
                },
            }
            for i in line_indexes
        ]
        original = pd.DataFrame(rows, columns=["_idx", *LINE_COLUMNS])
        edited = st.data_editor(
            original,
            num_rows="dynamic" if editable else "fixed",
            disabled=not editable,
            hide_index=True,
            width="stretch",
            column_config={
                "_idx": None,
                "description": st.column_config.TextColumn("Description", width="large"),
                "quantity": st.column_config.TextColumn("Qty"),
                "unit_price": st.column_config.TextColumn("Unit price"),
                "amount": st.column_config.TextColumn("Amount"),
            },
            key="lines",
        )
        line_msgs = [
            m for k, ms in messages_by_field.items() if k.startswith("line_items") for m in ms
        ]
        for msg in dict.fromkeys(line_msgs):
            st.caption(f"⚠️ {msg}")

        dup_flagged = "possible_duplicate" in doc["review_reasons"]
        note = st.text_input(
            "Note (required to approve a possible duplicate)" if dup_flagged else "Note (optional)",
            disabled=not editable,
        )
        c1, c2 = st.columns(2)
        save = c1.form_submit_button("Save changes", disabled=not editable)
        save_approve = c2.form_submit_button(
            "Save and approve", type="primary", disabled=not editable
        )


def collect_changes() -> tuple[list[dict], list[int]]:
    changes = []
    for name, value in header_inputs.items():
        old = (header.get(name) or {}).get("value_text")
        if blank(value) != blank(old):
            changes.append({"field_name": name, "line_item_index": None, "value": blank(value)})
    kept = set()
    next_index = (max(line_indexes) + 1) if line_indexes else 0
    for _, row in edited.iterrows():
        idx = row["_idx"]
        if idx is None or pd.isna(idx):
            if not any(blank(row[c]) for c in LINE_COLUMNS):
                continue  # an empty new row
            idx, is_new = next_index, True
            next_index += 1
        else:
            idx, is_new = int(idx), False
            kept.add(idx)
        for c in LINE_COLUMNS:
            old = None if is_new else (by_key.get(f"line_items.{idx}.{c}") or {}).get("value_text")
            if blank(row[c]) != blank(old):
                changes.append({"field_name": c, "line_item_index": idx, "value": blank(row[c])})
    deleted = [i for i in line_indexes if i not in kept]
    return changes, deleted


if editable and (save or save_approve):
    changes, deleted = collect_changes()
    try:
        if changes or deleted:
            api.correct(doc_id, changes, deleted)
        if save_approve:
            api.approve(doc_id, note=note.strip() or None)
            st.success("Invoice approved.")
            st.session_state.pop("review_doc_id", None)
            st.balloons()
            st.page_link("pages/2_Review_Queue.py", label="Back to the review queue", icon="📋")
            st.stop()
    except ApiError as exc:
        if exc.reasons:
            st.error(
                "Not approved yet — please fix:\n"
                + "\n".join(
                    f"- {reason_text('possible_duplicate' if r == 'not_duplicate' else r)}"
                    for r in exc.reasons
                )
            )
        else:
            st.error(exc.message)
    else:
        st.rerun()

# ---------- reject ----------

if editable:
    with st.expander("Reject this invoice"):
        reason = st.text_input("Reason (required)", key="reject-reason")
        if st.button("Reject", disabled=len(reason.strip()) < 3):
            try:
                api.reject(doc_id, reason.strip())
            except ApiError as exc:
                st.error(exc.message)
            else:
                st.session_state.pop("review_doc_id", None)
                st.success("Invoice rejected.")
                st.page_link("pages/2_Review_Queue.py", label="Back to the review queue", icon="📋")
                st.stop()

# ---------- duplicate side by side ----------

dup_id = doc.get("duplicate_document_id")
if dup_id:
    st.divider()
    st.subheader("Possible duplicate — compare")
    try:
        other = api.get_document(dup_id)
    except ApiError as exc:
        st.error(exc.message)
    else:
        a, b = st.columns(2)
        other_header = {
            f["field_name"]: f["value_text"]
            for f in (other.get("extraction") or {}).get("fields", [])
            if f["line_item_index"] is None
        }
        for col, title_, values, d_id in (
            (
                a,
                "This invoice",
                {k: (header.get(k) or {}).get("value_text") for k in FIELD_LABELS},
                doc_id,
            ),
            (
                b,
                f"Earlier: {other['filename']} ({other['status'].replace('_', ' ')})",
                other_header,
                dup_id,
            ),
        ):
            with col:
                st.markdown(f"**{title_}**")
                st.table(
                    {
                        FIELD_LABELS[k]: [values.get(k) or "—"]
                        for k in ("vendor_name", "invoice_number", "invoice_date", "total")
                    }
                )
                try:
                    st.image(api.page_image(d_id, 1), width="stretch")
                except ApiError:
                    st.caption("No page image.")
