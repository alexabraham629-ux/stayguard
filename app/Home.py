"""StayGuard — Executive Overview (placeholder until Phase 5)."""

import streamlit as st

from stayguard.config import load_assumptions

st.set_page_config(page_title="StayGuard", layout="wide")

st.title("StayGuard")
st.write("Booking-risk copilot for student-housing marketplaces.")
st.info("Scaffold only: the Executive Overview is built in Phase 5.")
st.caption(load_assumptions()["project"]["synthetic_data_label"])
