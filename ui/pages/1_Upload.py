"""Upload invoices and watch them being processed."""

from datetime import datetime

import streamlit as st
from api_client import ApiError
from common import client, reason_text, require_login, status_badge

require_login()
st.title("Upload invoices")

MIME = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}

with st.form("upload", clear_on_submit=True):
    files = st.file_uploader(
        "PDF, JPG or PNG — up to 15 MB each",
        type=list(MIME),
        accept_multiple_files=True,
    )
    send = st.form_submit_button("Upload", type="primary")

if send and files:
    payload = [(f.name, f.getvalue(), MIME[f.name.rsplit(".", 1)[-1].lower()]) for f in files]
    try:
        results = client().upload(payload)
    except ApiError as exc:
        st.error(f"Upload failed: {exc.message}")
    else:
        ok = [r for r in results if r.get("document_id")]
        bad = [r for r in results if r.get("error")]
        if ok:
            st.success(f"{len(ok)} file(s) uploaded. They are being read now.")
        for r in bad:
            st.error(f"{r['filename']}: {r['error']}")


def _when(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone().strftime("%d %b %H:%M")


@st.fragment(run_every=3)
def recent_uploads() -> None:
    try:
        docs = client().list_documents(limit=30)
    except ApiError as exc:
        st.error(exc.message)
        return
    st.subheader("Recent uploads")
    if not docs:
        st.info("Nothing uploaded yet.")
        return
    cols = st.columns([3, 2, 2, 4, 1.4])
    for col, title in zip(cols, ["File", "Uploaded", "Status", "Details", ""], strict=True):
        col.markdown(f"**{title}**")
    for d in docs:
        c = st.columns([3, 2, 2, 4, 1.4])
        c[0].write(d["filename"])
        c[1].write(_when(d["created_at"]))
        c[2].markdown(status_badge(d["status"]))
        if d["status"] == "failed":
            c[3].caption(d.get("error_message") or "")
            if c[4].button("Retry", key=f"retry-{d['id']}"):
                try:
                    client().retry(d["id"])
                    st.toast(f"Retrying {d['filename']}")
                except ApiError as exc:
                    st.error(exc.message)
        elif d["status"] == "needs_review":
            c[3].caption("; ".join(reason_text(r) for r in d["review_reasons"]))
            if c[4].button("Open", key=f"open-{d['id']}"):
                st.session_state.review_doc_id = d["id"]
                st.switch_page("pages/3_Review_Invoice.py")


recent_uploads()
