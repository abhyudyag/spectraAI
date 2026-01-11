import json
import re
from core.llm.ai_framework_adaptor import AIFrameworkAdaptor
from agents.Sutra.prompts import SUTRA_MASTER_PROMPT
from core.rag.retriever import Retriever

class SutraAgent:
    def __init__(self, db_path, collection_name, prompt_type="coder", config=None):
        self.mode = "coder"
        self.config = config or {}
        
        # 1. Initialize Retriever for Code Context
        try:
            self.retriever = Retriever(db_path, collection_name)
        except Exception as e:
            print(f"⚠️ Retrieval init failed: {e}")
            self.retriever = None

        # 2. Initialize Wisdom (Optional)
        try:
            from core.rag.retriever import Retriever as WisdomRetriever
            self.wisdom_retriever = WisdomRetriever(db_path, "solvo_wisdom")
        except:
            self.wisdom_retriever = None

        # 3. Initialize Brain
        self.llm = AIFrameworkAdaptor()
        
        self.state = "IDLE"

    def _construct_prompt(self, task, plan_context, code_context):
        return f"""{SUTRA_MASTER_PROMPT}

# 1. THE APPROVED PLAN (IMPACT ANALYSIS)
{plan_context}

# 2. EXISTING CODE CONTEXT
{code_context}

# 3. CURRENT TASK
{task}
"""

    def _construct_reflection_prompt(self, original_code, task):
        return f"""
# SELF-CORRECTION TASK
You just wrote the following code for the task: "{task}"

```java
{original_code}
```

**Critique your work:**
1. Are there any syntax errors?
2. Did you follow the naming conventions found in the context?
3. Is error handling present?

**OUTPUT:**
Return the **FINAL, CORRECTED** JSON object with the 'files' and 'explanation' keys. Do not explain the corrections, just provide the fixed code.
"""

    def execute(self, user_input, session_data):
        """
        user_input: The specific instruction (e.g. "Implement the User.java changes")
        session_data: Contains 'uploaded_doc_content' (the plan).
        """
        self.state = "CODING"
        
        # 1. Retrieve specific code context
        code_context = self.retriever.get_context_for_request(user_input, top_k=5)
        
        # 2. Get the Plan
        plan_context = session_data.get("uploaded_doc_content", "No plan provided.")

        # 3. Construct Prompt & Generate Draft
        full_prompt = self._construct_prompt(user_input, plan_context, code_context)
        print("\n🧵 Sutra is weaving first draft...")
        draft_response = self.llm.generate_content(full_prompt)
        
        if not draft_response or not draft_response.text:
            session_data["last_agent_response"] = "🚨 Sutra returned empty response."
            self.state = "DONE"
            return

        # 4. Reflection Loop (The Upgrade)
        print("🪞 Sutra is reviewing and polishing the code...")
        reflection_prompt = self._construct_reflection_prompt(draft_response.text, user_input)
        final_response = self.llm.generate_content(reflection_prompt)
        
        # Fallback to draft if reflection fails empty
        response_text = final_response.text if (final_response and final_response.text) else draft_response.text

        # 5. Parse Output
        try:
            def extract_json(text):
                text = text.strip()
                s = text.find('{')
                if s == -1: return None
                balance = 0
                escape = False
                in_str = False
                for i in range(s, len(text)):
                    char = text[i]
                    if char == '"' and not escape: in_str = not in_str
                    if not in_str:
                        if char == '{': balance += 1
                        elif char == '}': balance -= 1
                    if char == '\\' and not escape: escape = True
                    else: escape = False
                    if balance == 0: return json.loads(text[s:i+1])
                return None

            result_json = extract_json(response_text)
            
            if not result_json:
                 # Fallback for raw text
                 session_data["last_agent_response"] = response_text
                 self.state = "DONE"
                 return

            # Format the output for the UI
            files = result_json.get("files", [])
            explanation = result_json.get("explanation", "Code generated.")
            
            formatted_output = f"### 🧵 Implementation Complete\n*{explanation}*\n\n"
            
            for file in files:
                path = file.get('path', 'Unknown')
                code = file.get('code_content', '')
                action = file.get('action', 'MODIFY')
                formatted_output += f"#### {action}: `{path}`\n```java\n{code}\n```\n\n"

            session_data["last_agent_response"] = formatted_output
            
            # Store code for Pramana (QA) to pick up later
            session_data["generated_code_context"] = formatted_output
            
            self.state = "DONE"

        except Exception as e:
            session_data["last_agent_response"] = f"🚨 Sutra Error: {e}\nRaw: {response_text}"
            self.state = "DONE"