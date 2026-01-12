import streamlit as st
import os
import sys
import chromadb
import json
from datetime import datetime

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agents.Solvo.agent import SolvoAgent 
from agents.Sutra.agent import SutraAgent
from agents.Pramana.agent import PramanaAgent
from core.utils.session_manager import SessionManager
from core.auth.user_manager import UserManager
from core.utils.config_loader import list_profiles, load_profile
import time
import threading
import uuid
import docx
from unstructured.partition.auto import partition

# --- Constants ---
DB_BASE_PATH = os.getenv("VECTOR_STORE_PATH", os.path.join(project_root, 'data', 'vector_store'))

# --- Page Configuration ---
st.set_page_config(
    page_title="Spectra AI",
    page_icon="🚀",
    layout="wide"
)

# Define the project root and the path for the feedback file
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
FEEDBACK_FILE_PATH = os.path.join(PROJECT_ROOT, 'data', 'solvo_feedback.jsonl')

def log_feedback(session_data):
    try:
        # Ensure the data directory exists
        os.makedirs(os.path.dirname(FEEDBACK_FILE_PATH), exist_ok=True)
        with open(FEEDBACK_FILE_PATH, 'a') as f:
            f.write(json.dumps(session_data) + '\n')
        print(f"📝 Feedback logged to {FEEDBACK_FILE_PATH}")
    except Exception as e:
        print(f"🚨 Feedback logging failed: {e}")

# --- Session State Init ---
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "username" not in st.session_state: st.session_state.username = None
if "agent" not in st.session_state: st.session_state.agent = None
if "messages" not in st.session_state: st.session_state.messages = []
if "agent_ready" not in st.session_state: st.session_state.agent_ready = False
if "is_thinking" not in st.session_state: st.session_state.is_thinking = False
if "session_data" not in st.session_state: st.session_state.session_data = {}

user_manager = UserManager()

# --- Login Page ---
def login_page():
    st.markdown("<h1 style='text-align: center;'>🔐 Spectra AI Login</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", type="primary", use_container_width=True)
            
            if submitted:
                if user_manager.authenticate(username, password):
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
        
        with st.expander("Register New User"):
            with st.form("register_form", clear_on_submit=True):
                new_user = st.text_input("New Username", key="reg_user")
                new_pass = st.text_input("New Password", type="password", key="reg_pass")
                reg_submitted = st.form_submit_button("Register")
                
                if reg_submitted:
                    if new_user and new_pass:
                        if user_manager.register(new_user, new_pass):
                            st.success("User registered! Please log in.")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("Username already exists.")
                    else:
                        st.error("Please fill all fields.")

if not st.session_state.logged_in:
    login_page()
    st.stop() # Stop execution here if not logged in

# --- Authenticated App ---

# Initialize SessionManager for the specific user
session_manager = SessionManager(username=st.session_state.username)

# --- Helper Functions ---
@st.cache_resource
def list_databases():
    if not os.path.isdir(DB_BASE_PATH):
        return []
    
    dbs = []
    
    # 1. Check if the root directory itself is a database
    if os.path.exists(os.path.join(DB_BASE_PATH, "chroma.sqlite3")):
        dbs.append("Default (Root)")

    # 2. Check for sub-directories that are databases
    sub_dbs = [d for d in os.listdir(DB_BASE_PATH)
            if os.path.isdir(os.path.join(DB_BASE_PATH, d)) and
               os.path.exists(os.path.join(DB_BASE_PATH, d, "chroma.sqlite3"))]
    dbs.extend(sub_dbs)
    
    return dbs

@st.cache_resource
def list_collections(db_name):
    try:
        # If user selected "Default (Root)", use DB_BASE_PATH directly
        if db_name == "Default (Root)":
            full_db_path = DB_BASE_PATH
        else:
            full_db_path = os.path.join(DB_BASE_PATH, db_name)
            
        client = chromadb.PersistentClient(path=full_db_path)
        return [c.name for c in client.list_collections()]
    except Exception:
        return []


def read_uploaded_file(uploaded_file):
    try:
        file_name = uploaded_file.name
        file_bytes = uploaded_file.getvalue()
        with open(file_name, "wb") as f:
            f.write(file_bytes)
        
        content = ""
        if file_name.endswith(".docx"):
            doc = docx.Document(file_name)
            content = "\n\n".join([para.text for para in doc.paragraphs if para.text.strip()])
        elif file_name.endswith((".txt", ".md")):
            content = file_bytes.decode("utf-8")
        elif file_name.endswith((".doc", ".ppt", ".pptx")):
            elements = partition(filename=file_name)
            content = "\n\n".join([str(el) for el in elements if hasattr(el, 'text') and el.text.strip()])
        
        os.remove(file_name)
        return content
    except Exception as e:
        if 'file_name' in locals() and os.path.exists(file_name):
            os.remove(file_name)
        return None

def run_agent_in_thread(agent_instance, prompt, session_data):
    """
    Runs the agent. NOTE: This function CANNOT modify st.session_state directly.
    It only modifies the mutable 'session_data' dictionary.
    """
    agent_instance.execute(prompt, session_data)
    # We do NOT set is_thinking=False here anymore. The main loop handles it.

# --- Sidebar ---
with st.sidebar:
    # CSS to tighten the sidebar layout
    st.markdown("""
        <style>
            [data-testid="stSidebarContent"] {
                padding-top: 1rem;
            }
        </style>
    """, unsafe_allow_html=True)

    # Header Row
    col_head, col_log = st.columns([4, 1])
    with col_head:
         st.markdown("# 🚀 Spectra AI")
    with col_log:
        if st.button("⏻", key="logout_btn", help="Logout"):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.agent = None
            st.rerun()

    st.markdown(f"**User:** `{st.session_state.username}`")
    
    st.divider()

    # --- SETUP SECTION (Grouped) ---
    with st.expander("⚙️ System Configuration", expanded=not st.session_state.agent_ready):
        # 1. Product Profile
        profiles = list_profiles()
        if not profiles:
            st.error("No profiles found!")
            st.stop()
        
        selected_profile_name = st.selectbox(
            "Product Profile", 
            profiles,
            format_func=lambda x: load_profile(x).get('display_name', x) if load_profile(x) else x
        )
        
        # Load and display profile info
        profile_config = load_profile(selected_profile_name)
        if profile_config and profile_config.get('description'):
            st.info(f"_{profile_config.get('description')}_")

        st.markdown("---")
        
        # 2. Knowledge Base
        db_list = list_databases()
        selected_db, selected_collection = None, None
        if db_list:
            selected_db = st.selectbox("Vector Database", db_list)
            if selected_db:
                selected_collection = st.selectbox("Collection", list_collections(selected_db))
        else:
            st.warning("No knowledge bases found.")

    # --- AGENT SECTION ---
    st.subheader("🤖 Agent Controller")
    
    available_agents = {"Solvo": SolvoAgent, "Sutra": SutraAgent, "Pramana": PramanaAgent}
    selected_agent_name = st.selectbox("Select Agent", list(available_agents.keys()), label_visibility="collapsed")
    
    # Agent Description / Mode
    agent_mode = None
    if selected_agent_name == "Solvo":
        agent_mode = st.radio(
            "Mode", 
            ("solvo", "archivist"), 
            format_func=lambda x: "Solution Architect" if x == "solvo" else "Codebase Q&A",
            horizontal=True
        )
    elif selected_agent_name == "Sutra":
         agent_mode = "coder" 
         st.caption("Mode: **Senior Developer**")
    elif selected_agent_name == "Pramana":
        agent_mode = "qa" 
        st.caption("Mode: **QA Automation**")

    # Primary Action Button
    if st.button("🚀 Initialize Agent", type="primary", use_container_width=True):
        if selected_db and selected_collection and selected_agent_name and agent_mode:
            with st.spinner("Initializing..."):
                # Handle the special "Default (Root)" case
                if selected_db == "Default (Root)":
                    full_db_path = DB_BASE_PATH
                else:
                    full_db_path = os.path.join(DB_BASE_PATH, selected_db)
                
                # Instantiate
                AgentClass = available_agents[selected_agent_name]
                st.session_state.agent = AgentClass(
                    full_db_path, 
                    selected_collection, 
                    prompt_type=agent_mode,
                    config=profile_config # Pass the loaded profile config
                )
                st.session_state.selected_agent_name = selected_agent_name
                st.session_state.current_profile = selected_profile_name
                
                st.session_state.agent_ready = True
                st.session_state.messages = [] 
                st.session_state.is_thinking = False
                st.session_state.session_data = {
                    "session_id": f"streamlit_session_{uuid.uuid4()}",
                    "conversation_history": [],
                    "rag_context": None,
                    "final_solution": None
                }
            st.rerun()
    
    # --- HISTORY SECTION ---
    st.divider()
    with st.expander("💾 Session History", expanded=False):
        # Save
        if st.session_state.agent_ready:
            st.caption("Save Current Session")
            with st.form("save_session_form"):
                save_name = st.text_input("Name", value=f"Session {datetime.now().strftime('%H:%M')}")
                if st.form_submit_button("Save", use_container_width=True):
                    if save_name:
                        try:
                            session_manager.save_session(
                                session_id=st.session_state.session_data.get("session_id", "unknown"),
                                session_data=st.session_state.session_data,
                                agent_state=st.session_state.agent.state,
                                agent_name=st.session_state.selected_agent_name,
                                agent_mode=st.session_state.agent.mode,
                                db_path=st.session_state.agent.db_path,
                                collection_name=st.session_state.agent.collection_name,
                                session_name=save_name,
                                profile_config=st.session_state.agent.config,
                                profile_name=st.session_state.get("current_profile")
                            )
                            st.success("Saved!")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

        # Load
        st.caption("Load Previous Session")
        sessions = session_manager.list_sessions()
        if sessions:
            session_options = {s["id"]: f"{s.get('name', s['filename'])} ({s['timestamp'][:10]})" for s in sessions}
            selected_session_id = st.selectbox("Select:", list(session_options.keys()), format_func=lambda x: session_options[x], key="session_selector", label_visibility="collapsed")
            
            if st.button("📂 Load Selected", use_container_width=True):
                 loaded_data = session_manager.load_session(selected_session_id)
                 if loaded_data:
                     with st.spinner("Restoring..."):
                         # extract data
                         l_agent_name = loaded_data.get("agent_name")
                         l_agent_mode = loaded_data.get("agent_mode")
                         l_db_path = loaded_data.get("db_path") or os.path.join(DB_BASE_PATH, "default_db") 
                         l_collection = loaded_data.get("collection_name", "default_collection")
                         l_state = loaded_data.get("agent_state")
                         l_session_data = loaded_data.get("session_data", {})
                         l_profile = loaded_data.get("profile_config", {})
                         
                         # Re-init agent
                         AgentClass = available_agents.get(l_agent_name, SolvoAgent)
                         st.session_state.agent = AgentClass(
                             l_db_path, 
                             l_collection, 
                             prompt_type=l_agent_mode,
                             config=l_profile
                         )
                         st.session_state.agent.state = l_state
                         st.session_state.selected_agent_name = l_agent_name
                         st.session_state.current_profile = loaded_data.get("profile_name", "Unknown")
                         st.session_state.agent_ready = True
                         st.session_state.messages = []
                         
                         if "conversation_history" in l_session_data:
                             st.session_state.messages = l_session_data["conversation_history"]
                         
                         st.session_state.session_data = l_session_data
                         st.session_state.is_thinking = False
                         st.rerun()
        else:
            st.info("No saved sessions.")


# --- Main Chat ---
if st.session_state.agent_ready:
    # Display agent name and mode
    agent_display_name = st.session_state.get("selected_agent_name", "Agent")
    profile_display = st.session_state.get("current_profile", "Default")
    
    if agent_display_name == "Solvo":
        mode_display_name = "Solution Architect" if st.session_state.agent.mode == 'solvo' else "Codebase Q&A"
    elif agent_display_name == "Sutra":
        mode_display_name = "Senior Developer"
    elif agent_display_name == "Pramana":
        mode_display_name = "QA Automation Engineer"
    else:
        mode_display_name = "Standard"

    st.info(f"**Profile:** `{profile_display}` | **Agent:** `{agent_display_name}` | **Mode:** `{mode_display_name}` | **KB:** `{st.session_state.agent.retriever.collection.name}`")
    
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # --- CRITICAL FIX: Check for response AND update state ---
    # If we find a response in the shared dictionary, it means the thread finished.
    if "last_agent_response" in st.session_state.session_data and st.session_state.session_data["last_agent_response"]:
        response_text = st.session_state.session_data.pop("last_agent_response")
        
        # 1. Update UI
        st.session_state.messages.append({"role": "assistant", "content": response_text})
        
        # 2. CRITICAL: Turn off the spinner flag HERE, on the main thread
        st.session_state.is_thinking = False
        
        # 3. Auto-Save Session
        try:
            session_manager.save_session(
                session_id=st.session_state.session_data.get("session_id", "unknown"),
                session_data=st.session_state.session_data,
                agent_state=st.session_state.agent.state,
                agent_name=st.session_state.selected_agent_name,
                agent_mode=st.session_state.agent.mode,
                db_path=st.session_state.agent.db_path,
                collection_name=st.session_state.agent.collection_name,
                profile_config=st.session_state.agent.config,
                profile_name=st.session_state.get("current_profile")
            )
        except Exception as e:
            print(f"Auto-save failed: {e}")

        # 4. Rerun to refresh the UI and show the input box
        st.rerun()

    # --- Show Spinner logic ---
    if st.session_state.is_thinking:
        with st.chat_message("assistant"):
            st.spinner("Solvo is thinking...")
        time.sleep(2) # Check again in 2s
        st.rerun()

    # --- Input Areas ---
    # Only show inputs if NOT thinking
    if not st.session_state.is_thinking:
        
        if st.session_state.agent.mode == 'solvo':
            # State 0: ANALYZING (Initial Request)
            if st.session_state.agent.state == "ANALYZING":
                st.divider()
                with st.form("solvo_input"):
                    uploaded = st.file_uploader("Upload Document (Optional)", type=["docx", "txt", "md"])
                    text = st.text_area("Requirement / Comments:")
                    if st.form_submit_button("Start Analysis", type="primary"):
                        content = ""
                        if uploaded: content = read_uploaded_file(uploaded)
                        
                        full_prompt = f"DOC:\n{content}\n\nREQ:\n{text}"
                        st.session_state.messages.append({"role": "user", "content": text or f"Analyzing {uploaded.name}..."})
                        
                        st.session_state.is_thinking = True
                        threading.Thread(target=run_agent_in_thread, args=(st.session_state.agent, full_prompt, st.session_state.session_data)).start()
                        st.rerun()

            # State 1: CLARIFYING (Chat)
            elif st.session_state.agent.state == "CLARIFYING":
                if prompt := st.chat_input("Answer Solvo's questions..."):
                    st.session_state.messages.append({"role": "user", "content": prompt})
                    st.session_state.is_thinking = True
                    threading.Thread(target=run_agent_in_thread, args=(st.session_state.agent, prompt, st.session_state.session_data)).start()
                    st.rerun()
            
            # State 2: DONE (Reset option)

            elif st.session_state.agent.state == "DONE":
                # --- FEEDBACK FORM ---
                st.divider()
                with st.form("feedback_form"):
                    st.write("### Rate this Solution")
                    rating = st.number_input("Rating (1-5)", min_value=1, max_value=5, step=1)
                    comment = st.text_area("Comment (Optional)")
                    if st.form_submit_button("Submit Feedback"):
                        feedback_data = st.session_state.session_data.copy()
                        feedback_data["rating"] = rating
                        feedback_data["comment"] = comment
                        log_feedback(feedback_data)
                        st.toast("Feedback submitted!")
                        # Optionally reset after feedback
                        st.session_state.agent.state = "ANALYZING"
                        st.session_state.messages = []
                        st.rerun()

                st.divider()
                if st.button("Start New Analysis Without Feedback"):
                     st.session_state.agent.state = "ANALYZING"
                     st.session_state.messages = []
                     st.rerun()

        elif st.session_state.agent.mode == 'archivist':
            if prompt := st.chat_input("Ask about the codebase..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                st.session_state.is_thinking = True
                threading.Thread(target=run_agent_in_thread, args=(st.session_state.agent, prompt, st.session_state.session_data)).start()
                st.rerun()

        elif st.session_state.agent.mode == 'coder': # Sutra
             # State 0: IDLE (Waiting for task)
             if st.session_state.agent.state == "IDLE" or st.session_state.agent.state == "DONE":
                st.divider()
                st.markdown("### 🧵 Sutra Task Input")
                
                with st.form("sutra_input"):
                    uploaded = st.file_uploader("Upload Plan / Impact Analysis (Optional)", type=["docx", "txt", "md", "json"])
                    task_instruction = st.text_area("Implementation Task (e.g. 'Implement the user registration service'):")
                    
                    if st.form_submit_button("Start Coding", type="primary"):
                        content = ""
                        if uploaded: 
                            content = read_uploaded_file(uploaded)
                            st.session_state.session_data["uploaded_doc_content"] = content
                        
                        prompt_text = task_instruction or f"Implementing based on {uploaded.name}..."
                        st.session_state.messages.append({"role": "user", "content": prompt_text})
                        
                        st.session_state.is_thinking = True
                        threading.Thread(target=run_agent_in_thread, args=(st.session_state.agent, prompt_text, st.session_state.session_data)).start()
                        st.rerun()

        elif st.session_state.agent.mode == 'qa': # Pramana
            st.subheader("Verification Phase")
            
            # Check for context from Sutra
            existing_code = st.session_state.session_data.get("generated_code_context")
            
            if existing_code:
                st.success("✅ Code Context loaded from Sutra session.")
            else:
                st.warning("⚠️ No code found in session history. Tests may be generic.")

            if p := st.chat_input("Describe tests to generate (e.g. 'Test boundary conditions for discount'):"):
                st.session_state.messages.append({"role": "user", "content": p})
                st.session_state.is_thinking = True
                threading.Thread(target=run_agent_in_thread, args=(st.session_state.agent, p, st.session_state.session_data)).start()
                st.rerun()

else:
    st.info("👈 Initialize the Platform from the sidebar.")
