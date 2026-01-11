import json
import re
import os
from core.llm.ai_framework_adaptor import AIFrameworkAdaptor
from core.rag.retriever import Retriever
from agents.Solvo.tools.doc_generator import save_solution_to_doc
# Ensure prompts are imported correctly. If in same dir, use .prompts
from .prompts import (
    get_prompt_by_profile, 
    CODE_EXPERT_PROMPT, 
    MASTER_PROMPT,
    D1_REQ_ANALYSIS_PROMPT,
    D1_SCOPE_IMPACT_PROMPT,
    D1_EPIC_BREAKDOWN_PROMPT
)

# --- HELPER: ROBUST JSON EXTRACTOR ---
def extract_first_json_block(text):
    text = text.strip()
    start_index = text.find('{')
    if start_index == -1: return None
    balance = 0
    is_inside_string = False
    escape_next = False
    for i in range(start_index, len(text)):
        char = text[i]
        if char == '"' and not escape_next: is_inside_string = not is_inside_string
        if not is_inside_string:
            if char == '{': balance += 1
            elif char == '}': balance -= 1
        if char == '\\' and not escape_next: escape_next = True
        else: escape_next = False
        if balance == 0 and i > start_index:
            try: return json.loads(text[start_index : i+1])
            except json.JSONDecodeError: continue
    return None

class SolvoAgent:
    def __init__(self, db_path, collection_name, prompt_type="solvo", config=None):
        self.db_path = db_path
        self.collection_name = collection_name
        self.config = config or {}
        
        # 1. Determine Profile & Workflow
        self.profile_id = self.config.get("profile_id", "ensemble_v1")
        self.mode = prompt_type
        
        if "digital" in self.profile_id.lower():
            self.workflow = "digital_one"
            self.states = ["REQ_ANALYSIS", "SCOPE_IMPACT", "EPIC_BREAKDOWN", "DONE"]
            print(f"🤖 Solvo initialized in DigitalOne Workflow")
        else:
            self.workflow = "ensemble"
            self.states = ["ANALYZING", "CLARIFYING", "DONE"]
            print(f"🤖 Solvo initialized in Ensemble Workflow")
            
        self.state = self.states[0]
        self.accumulated_doc_content = "" # Initialize buffer for D1 reports

        # 2. Select Initial Prompt (for Ensemble/Default)
        if self.mode == "archivist":
             self.master_prompt = CODE_EXPERT_PROMPT
        else:
             # This helper needs to be in prompts.py
             self.master_prompt = get_prompt_by_profile(self.profile_id)
        
        # 3. Initialize Services
        try:
            self.retriever = Retriever(db_path, collection_name)
            self.llm = AIFrameworkAdaptor()
            print(f"🤖 Agent ready. Profile: {self.profile_id}")
        except Exception as e:
            print(f"🚨 FATAL: Could not initialize agent: {e}")
            self.llm = None
            self.state = "DONE"

    # --- PROMPT CONSTRUCTORS ---
    
    def _construct_ensemble_prompt(self, user_input, rag_context, conversation_history):
        history_str = ""
        for i, turn in enumerate(conversation_history):
            if i == len(conversation_history) - 1 and turn['content'] == user_input: continue
            role_label = "Solvo" if turn['role'] == 'assistant' else "User"
            history_str += f"[{role_label}]: {turn['content']}\n\n"
        return f"{self.master_prompt}\n{rag_context}\n# CONVERSATION HISTORY\n{history_str}\n\n# LATEST USER INPUT\n\n{user_input}"

    def _construct_d1_prompt(self, state, user_input, rag_context):
        if state == "REQ_ANALYSIS":
            return f"{D1_REQ_ANALYSIS_PROMPT}\n{rag_context}\n# REQUIREMENTS\n{user_input}"
        elif state == "SCOPE_IMPACT":
            return f"{D1_SCOPE_IMPACT_PROMPT}\n{rag_context}\n# PREVIOUS ANALYSIS (CONTEXT)\n{self.accumulated_doc_content}"
        elif state == "EPIC_BREAKDOWN":
            return f"{D1_EPIC_BREAKDOWN_PROMPT}\n# PREVIOUS ANALYSIS (CONTEXT)\n{self.accumulated_doc_content}"
        return ""

    # --- EXECUTION LOGIC ---

    def execute(self, user_input, session_data):
        if not self.llm:
            session_data["last_agent_response"] = "🚨 Agent is not initialized. Cannot proceed."
            return

        # === WORKFLOW DISPATCHER ===
        if self.mode == "archivist":
            self._execute_archivist(user_input, session_data)
        elif self.workflow == "digital_one":
            self._execute_digital_one(user_input, session_data)
        else:
            self._execute_ensemble(user_input, session_data)

    # --- WORKFLOW IMPLEMENTATIONS ---

    def _execute_archivist(self, user_input, session_data):
        rag_context = self.retriever.get_context_for_request(user_input)
        session_data.setdefault("conversation_history", []).append({"role": "user", "content": user_input})
        prompt = self._construct_ensemble_prompt(user_input, rag_context, session_data["conversation_history"])
        
        print("\n⏳ Archivist is thinking...")
        response = self.llm.generate_content(prompt)
        
        if response and response.text:
            session_data["last_agent_response"] = response.text
            session_data.setdefault("conversation_history", []).append({"role": "assistant", "content": response.text})
        else:
            session_data["last_agent_response"] = "🚨 No response received."

    def _execute_ensemble(self, user_input, session_data):
        prompt_to_send = ""
        rag_context = ""
        
        if self.state == "ANALYZING":
            rag_context = self.retriever.get_context_for_request(user_input)
            session_data["rag_context"] = rag_context
            prompt_to_send = self._construct_ensemble_prompt(user_input, rag_context, [])
        elif self.state == "CLARIFYING":
            rag_context = session_data.get("rag_context", "") 
            session_data.setdefault("conversation_history", []).append({"role": "user", "content": user_input})
            prompt_to_send = self._construct_ensemble_prompt(user_input, rag_context, session_data["conversation_history"])
        
        print("\n⏳ Solvo (Ensemble) is thinking...")
        response = self.llm.generate_content(prompt_to_send)
        self._handle_json_response(response, session_data, is_digital_one=False)

    def _execute_digital_one(self, user_input, session_data):
        prompt_to_send = ""
        rag_context = ""

        if self.state == "REQ_ANALYSIS":
            print("📝 D1 Step 1: Requirement Analysis...")
            rag_context = self.retriever.get_context_for_request(user_input)
            prompt_to_send = self._construct_d1_prompt("REQ_ANALYSIS", user_input, rag_context)
            
        elif self.state == "SCOPE_IMPACT":
            print("🎯 D1 Step 2: Scope & Impact...")
            # Use accumulated content as context for retrieval to find deeper links
            rag_context = self.retriever.get_context_for_request(self.accumulated_doc_content[:1000])
            prompt_to_send = self._construct_d1_prompt("SCOPE_IMPACT", "", rag_context)

        elif self.state == "EPIC_BREAKDOWN":
            print("🧩 D1 Step 3: Epic Breakdown...")
            prompt_to_send = self._construct_d1_prompt("EPIC_BREAKDOWN", "", "")

        print("\n⏳ Solvo (DigitalOne) is processing...")
        response = self.llm.generate_content(prompt_to_send)
        self._handle_json_response(response, session_data, is_digital_one=True)

    # --- COMMON RESPONSE HANDLER ---
    def _handle_json_response(self, response, session_data, is_digital_one):
        if not response or not response.text:
             self.state = "DONE"
             session_data["last_agent_response"] = "🚨 Agent returned an empty response."
             return

        try:
            response_json = extract_first_json_block(response.text)
            if not response_json:
                  # Fallback regex
                  json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
                  if json_match: response_json = json.loads(json_match.group(0))
            
            if not response_json:
                  self.state = "DONE"
                  session_data["last_agent_response"] = f"🚨 Invalid Output:\n\n{response.text}"
                  return

            # --- D1 STATE TRANSITIONS ---
            if is_digital_one:
                markdown_part = response_json.get("markdown_content", "")
                self.accumulated_doc_content += "\n\n" + markdown_part
                
                if self.state == "REQ_ANALYSIS":
                    self.state = "SCOPE_IMPACT"
                    session_data["last_agent_response"] = f"✅ **Requirement Analysis Complete.**\n\n{markdown_part[:300]}...\n\n_Proceeding to Scope Analysis..._"
                elif self.state == "SCOPE_IMPACT":
                    self.state = "EPIC_BREAKDOWN"
                    session_data["last_agent_response"] = f"✅ **Scope Analysis Complete.**\n\n{markdown_part[:300]}...\n\n_Proceeding to Epic Breakdown..._"
                elif self.state == "EPIC_BREAKDOWN":
                    self.state = "DONE"
                    # Save Final Doc
                    doc_filename = f"ProductSpec_{session_data['session_id']}.docx"
                    save_solution_to_doc({"markdown_report": self.accumulated_doc_content, "summary": "DigitalOne Product Spec"}, doc_filename, is_digital_one=True)
                    session_data["last_agent_response"] = f"✅ **Process Complete!**\n\n📄 Generated: `{doc_filename}`"
                return

            # --- ENSEMBLE STATE TRANSITIONS ---
            if "ask_questions" in response_json:
                self.state = "CLARIFYING"
                questions = "\n".join([f"* {q}" for q in response_json["ask_questions"]])
                session_data.setdefault("conversation_history", []).append({"role": "assistant", "content": questions})
                session_data["last_agent_response"] = f"🤖 **Questions:**\n\n{questions}"
            
            elif "generate_solution" in response_json:
                self.state = "DONE"
                solution = response_json["generate_solution"]
                session_data["final_solution"] = solution
                
                doc_filename = f"ImpactAnalysis_{session_data['session_id']}.docx"
                save_solution_to_doc(solution, doc_filename, is_digital_one=False)
                
                summary = f"✅ **Analysis Complete!**\n📄 Doc: `{doc_filename}`\n\n### Summary\n{solution.get('summary', 'N/A')}"
                session_data["last_agent_response"] = summary

        except Exception as e:
            self.state = "DONE"
            session_data["last_agent_response"] = f"🚨 Processing Error: {e}"