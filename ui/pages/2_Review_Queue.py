"""Invoices waiting for a person, oldest first."""

import streamlit as st
from api_client import ApiError
from common import client, human_age, reason_text, require_login

require_login()
st.title("Review queue")

try:
    items = client().queue()
except ApiError as exc:
    st.error(exc.message)
    st.stop()

if not items:
    st.success("Nothing to review. 🎉")
    st.stop()

oldest = max(i["age_seconds"] for i in items)
st.caption(f"{len(items)} invoice(s) waiting · oldest has waited {human_age(oldest)}")

widths = [3, 2, 1.5, 5, 1, 1]
for col, title in zip(
    st.columns(widths),
    ["Vendor", "Invoice no.", "Total", "Why it needs a look", "Waiting", ""],
    strict=True,
):
    col.markdown(f"**{title}**")
for item in items:
    c = st.columns(widths)
    c[0].write(item["vendor_name"] or f"_{item['filename']}_")
    c[1].write(item["invoice_number"] or "—")
    c[2].write(item["total"] or "—")
    c[3].write("\n".join(f"- {reason_text(r)}" for r in item["review_reasons"]) or "—")
    c[4].write(human_age(item["age_seconds"]))
    if c[5].button("Open", key=f"open-{item['id']}", type="primary"):
        st.session_state.review_doc_id = item["id"]
        st.switch_page("pages/3_Review_Invoice.py")
