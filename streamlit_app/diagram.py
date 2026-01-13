import streamlit as st
import sidebar
import streamlit.components.v1 as components

def diagram_page():
    """Diagram page for visualizations."""
    st.title("Diagram")
    
    sidebar.render_sidebar()
    
    st.markdown("### AWS Architecture Diagram")
    
    # Embed the diagram from the URL
    diagram_url = "https://mertali07.github.io/aws_presentation/"
    
    # Use iframe to embed the external diagram
    components.iframe(
        src=diagram_url,
        width=None,
        height=800,
        scrolling=True
    )
    
    st.markdown("---")
    st.markdown(f"**Source:** [AWS Presentation]({diagram_url})")
