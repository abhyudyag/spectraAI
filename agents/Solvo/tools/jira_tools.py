import os
import json
import re
import docx
import sys
from jira import JIRA
# Use absolute imports from the project root and correct the typo
from core.llm.ai_framework_adaptor import AIFrameworkAdapter
from agents.Solvo.prompts import STORY_CREATOR_PROMPT

# --- CONFIGURATION ---
# The environment variables will now be loaded inside the connect_to_jira function
# to prevent the app from crashing at startup if they are not set.

def connect_to_jira():
    """
    Connects to Jira using configuration from config/jira_config.json.
    Raises ConnectionError if variables are missing or connection fails.
    """
    try:
        # Construct path to config/jira_config.json relative to this file
        # agents/Solvo/tools/jira_tools.py -> ../../../config/jira_config.json
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        config_path = os.path.join(base_path, "config", "jira_config.json")
        
        with open(config_path, "r") as f:
            config = json.load(f)

        JIRA_SERVER = config["jira_server"]
        JIRA_USERNAME = config["jira_username"]
        JIRA_API_TOKEN = config["jira_api_token"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        # Raise an exception that the UI layer can catch and display gracefully.
        raise ConnectionError(f"Error loading Jira config: {e}. Please ensure config/jira_config.json exists and has correct keys.")

    try:
        jira = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_USERNAME, JIRA_API_TOKEN))
        print(f"✅ Successfully connected to Jira as {JIRA_USERNAME}.")
        return jira
    except Exception as e:
        # Re-raise the exception so the UI can handle it.
        raise ConnectionError(f"Failed to connect to Jira server at '{JIRA_SERVER}'. Please check the server URL and your credentials. Error: {e}")


def read_doc_content(file_path):
    """Reads all text from a .docx file."""
    try:
        doc = docx.Document(file_path)
        full_text = [para.text for para in doc.paragraphs]
        return '\n\n'.join(full_text)
    except Exception as e:
        print(f"🚨 Error reading document: {e}")
        return None

def create_stories_in_jira(jira, stories, project_key):
    """Loops through the list of stories and creates them in Jira."""
    print(f"\nAttempting to create {len(stories)} stories in project '{project_key}'...")
    for story in stories:
        summary = story.get("summary")
        description = story.get("description", "No description provided.")
        ac = story.get("acceptance_criteria", [])
        
        # Format description for Jira
        full_description = f"{description}\n\n*Acceptance Criteria:*\n"
        for criteria in ac:
            full_description += f"* {criteria}\n"
        
        issue_dict = {
            'project': {'key': project_key},
            'summary': summary,
            'description': full_description,
            'issuetype': {'name': 'Story'}
        }
        
        try:
            new_issue = jira.create_issue(fields=issue_dict)
            print(f"  ✅ Created: [{new_issue.key}] - {summary}")
        except Exception as e:
            print(f"  🚨 FAILED to create story '{summary}'. Error: {e}")

def main():
    print("--- 🤖 AI Story Creator ---")
    
    # 1. Get Jira Project Key
    project_key = input("Enter your Jira Project Key (e.g., SOLVO): ").strip().upper()
    
    # 2. Get Document Path
    doc_path = input("Enter the path to the FINAL, approved .docx file: ").strip()
    if not os.path.exists(doc_path) or not doc_path.endswith(".docx"):
        print("🚨 Invalid file path.")
        return
        
    document_content = read_doc_content(doc_path)
    if not document_content:
        return
        
    print(f"\n📄 Document loaded successfully ({len(document_content)} chars).")
    
    # 3. Initialize LLM
    try:
        llm = AIFrameworkAdapter()
    except Exception as e:
        print(f"🚨 FATAL: Could not initialize the AI Framework Adapter. {e}")
        return

    # 4. Generate Stories from Document
    prompt = f"{STORY_CREATOR_PROMPT}\n# FINALIZED DOCUMENT CONTENT\n\n{document_content}"
    
    print("⏳ Asking AI to analyze document and generate user stories...")
    response = llm.generate_content(prompt)
    
    if not response or not response.text:
        print("🚨 Agent returned an empty response. Cannot proceed.")
        return
        
    try:
        # Find and parse the JSON response
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if not json_match:
            print("🚨 Agent returned non-JSON. Raw response:")
            print(response.text)
            return
            
        story_json = json.loads(json_match.group(0))
        stories_to_create = story_json.get("user_stories", [])
        
        if not stories_to_create:
            print("🚨 AI did not generate any user stories.")
            return

        print("\n--- 🤖 AI Generated Stories ---")
        for i, story in enumerate(stories_to_create):
            print(f"\nSTORY {i+1}:")
            print(f"  Summary: {story.get('summary')}")
            print(f"  Desc: {story.get('description')}")
            print(f"  AC: {story.get('acceptance_criteria')}")
        print("-------------------------------")

        # 5. Get User Approval
        approval = input("\nDo you want to create these stories in Jira? (y/n): ").lower().strip()
        
        if approval == 'y':
            try:
                jira = connect_to_jira()
                if jira:
                    create_stories_in_jira(jira, stories_to_create, project_key)
                else:
                    print("🚨 Cannot create stories. Jira connection failed.")
            except ConnectionError as e:
                print(f"🚨 Jira connection failed: {e}")
        else:
            print("Story creation cancelled.")

    except Exception as e:
        print(f"🚨 An error occurred: {e}")

if __name__ == "__main__":
    main()