import streamlit as st

# Import page modules
from home import home_page
from diagram import diagram_page

st.set_page_config(page_title="Vergi Asistanı", page_icon="🤖", layout="wide")

# Navigation
page = st.navigation([
    st.Page(home_page, title="Home", icon="🏠"),
    st.Page(diagram_page, title="Diagram", icon="📊"),
])

page.run()
