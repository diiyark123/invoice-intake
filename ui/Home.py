"""Streamlit entry point: login, then role-based navigation (clerks never see manager pages)."""

import streamlit as st
from api_client import ApiError
from common import client, current_user

st.set_page_config(page_title="Invoice Intake", page_icon="🧾", layout="wide")


def login_page() -> None:
    st.title("Invoice Intake — Meridian Supplies")
    st.write("Log in to upload and review supplier invoices.")
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")
    if submitted:
        try:
            user = client().login(email.strip(), password)
        except ApiError as exc:
            st.error("Wrong email or password." if exc.status == 401 else exc.message)
        else:
            st.session_state.user = {"role": user["role"], "name": user["display_name"]}
            st.rerun()


def logout() -> None:
    for key in ("user", "api", "review_doc_id"):
        st.session_state.pop(key, None)
    st.rerun()


user = current_user()
if user is None:
    st.navigation([st.Page(login_page, title="Log in", icon="🔑")]).run()
else:
    pages = [
        st.Page("pages/1_Upload.py", title="Upload", icon="📤", default=True),
        st.Page("pages/2_Review_Queue.py", title="Review queue", icon="📋"),
        st.Page("pages/3_Review_Invoice.py", title="Review invoice", icon="🔍"),
    ]
    if user["role"] == "manager":
        pages += [
            st.Page("pages/4_Dashboard.py", title="Dashboard", icon="📊"),
            st.Page("pages/5_Settings.py", title="Settings", icon="⚙️"),
        ]
    with st.sidebar:
        st.write(f"Logged in as **{user['name']}**")
        if st.button("Log out"):
            logout()
    st.navigation(pages).run()
