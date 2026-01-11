import streamlit as st
import os
import sys
import json
import re

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agents.Solvo.tools.jira_tools import connect_to_jira, create_stories_in_jira, read_doc_content
from agents.Solvo.prompts import STORY_CREATOR_PROMPT
from core.llm.ai_framework_adaptor import AIFrameworkAdapter

# --- Page Configuration ---
st.set_page_config(
    page_title="Jira Synchronization Tool",
    page_icon="🔄",
    layout="centered"
)

st.title("🔄 Jira Synchronization Tool")
st.markdown("Upload a finalized Impact Analysis document (.docx) to extract the user stories and push them to your Jira project.")

# --- Session State ---
if "stories_to_create" not in st.session_state:
    st.session_state.stories_to_create = []

# --- UI Components ---
uploaded_file = st.file_uploader("1. Upload Finalized Document", type=["docx"])

if uploaded_file:
    if st.button("Extract Stories from Document"):
        with st.spinner("Reading document and asking AI to generate stories..."):
            try:
                # Save temp file to read content
                with open(uploaded_file.name, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                document_content = read_doc_content(uploaded_file.name)
                os.remove(uploaded_file.name)

                if document_content:
                    llm = AIFrameworkAdapter()
                    prompt = f"{STORY_CREATOR_PROMPT}\n# FINALIZED DOCUMENT CONTENT\n\n{document_content}"
                    response = llm.generate_content(prompt)
                    
                    if response and response.text:
                        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if json_match:
                            story_json = json.loads(json_match.group(0))
                            st.session_state.stories_to_create = story_json.get("user_stories", [])
                            st.success(f"Successfully extracted {len(st.session_state.stories_to_create)} stories.")
                        else:
                            st.error("AI did not return a valid JSON format. Cannot extract stories.")
                    else:
                        st.error("AI returned an empty response.")
                else:
                    st.error("Could not read content from the document.")
            except Exception as e:
                st.error(f"An error occurred: {e}")

if st.session_state.stories_to_create:
    st.divider()
    st.subheader("🤖 AI Generated Stories")

    for i, story in enumerate(st.session_state.stories_to_create):
        with st.expander(f"**Story {i+1}:** {story.get('summary')}"):
            st.markdown(f"**Description:**\n{story.get('description', 'N/A')}")
            st.markdown(f"**Acceptance Criteria:**")
            for ac in story.get('acceptance_criteria', []):
                st.markdown(f"- {ac}")
    
    st.divider()
    st.subheader("🚀 Push to Jira")
    jira_project_key = st.text_input("2. Jira Project Key", placeholder="e.g., KEYSTONE")

    if st.button("Sync Stories to Jira", type="primary"):
        if not jira_project_key:
            st.warning("Please enter a Jira Project Key.")
        else:
            with st.spinner("Connecting to Jira and creating stories..."):
                try:
                    jira_conn = connect_to_jira()
                    if jira_conn:
                        create_stories_in_jira(jira_conn, st.session_state.stories_to_create, jira_project_key)
                        st.success(f"Successfully pushed {len(st.session_state.stories_to_create)} stories to Jira project {jira_project_key}!")
                        # Clear stories after pushing
                        st.session_state.stories_to_create = []
                    else:
                        st.error("Could not connect to Jira. Please check your JIRA environment variables.")
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")
