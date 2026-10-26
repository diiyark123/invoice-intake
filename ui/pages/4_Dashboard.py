"""Manager dashboard: volume, automation, queue health, corrections and AI cost."""

import streamlit as st
from api_client import ApiError
from common import FIELD_LABELS, client, require_login

require_login(role="manager")
st.title("Dashboard")

try:
    m = client().dashboard()
except ApiError as exc:
    st.error(exc.message)
    st.stop()


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


st.subheader("Invoices processed")
c = st.columns(3)
c[0].metric("Today", m["processed"]["today"])
c[1].metric("This week", m["processed"]["this_week"])
c[2].metric("This month", m["processed"]["this_month"])

st.subheader("How it's going this month")
c = st.columns(4)
c[0].metric("Approved automatically", pct(m["auto_approval_rate"]))
c[1].metric(
    "Waiting for review",
    m["queue_size"],
    help="Oldest has waited "
    + ("—" if m["oldest_in_queue_hours"] is None else f"{m['oldest_in_queue_hours']} hours"),
)
c[2].metric("Failed (need Retry)", m["failed"])
c[3].metric(
    "Avg. reading time",
    "—" if m["avg_processing_seconds"] is None else f"{m['avg_processing_seconds']} s",
)
if m["oldest_in_queue_hours"] is not None:
    st.caption(
        f"The oldest invoice in the review queue has waited {m['oldest_in_queue_hours']} hours."
    )

st.subheader("AI cost")
c = st.columns(3)
cost = m["llm_cost_per_invoice_usd"]
c[0].metric("Per invoice", "—" if cost is None else f"${cost:.4f}")
c[1].metric(
    f"Per month at {m['monthly_volume_assumed']:,} invoices",
    "—" if m["projected_monthly_cost_usd"] is None else f"${m['projected_monthly_cost_usd']:.2f}",
)
c[2].metric("Monthly volume at current pace", f"{m['projected_monthly_volume_at_current_pace']:,}")

st.subheader("Which values people fix most")
corrections = m["corrections_by_field"]
if not corrections:
    st.info("No corrections yet.")
else:
    rows = [
        {"Value": FIELD_LABELS.get(k, k.capitalize()), "Times corrected": v}
        for k, v in corrections.items()
    ]
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("A value that is corrected often is a good place to improve the extraction.")
