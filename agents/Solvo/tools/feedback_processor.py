# In feedback_processor.py
import git
import json
import re
import os
import docx
import tempfile

# --- CONFIGURATION ---
REPO_PATH = "/path/to/your/local/git/repo" # IMPORTANT: Set this to the path of your Git repository
FEEDBACK_LOG_FILE = "feedback.jsonl"
FINETUNING_DATASET_FILE = "finetuning_dataset.jsonl"

def process_feedback_logs():
    print("Loading feedback session data...")
    sessions = {}
    if not os.path.exists(FEEDBACK_LOG_FILE):
        print(f"Feedback log file not found: {FEEDBACK_LOG_FILE}")
        return
        
    with open(FEEDBACK_LOG_FILE, 'r') as f:
        for line in f:
            data = json.loads(line)
            sessions[data['session_id']] = data
    
    print(f"Loaded {len(sessions)} sessions.")

    repo = git.Repo(REPO_PATH)
    print("Scanning Git history for feedback references...")
    # Scan the last 1000 commits. Adjust as needed.
    commits = repo.iter_commits('main', max_count=1000, grep="Ref: session_id=")

    finetuning_examples = []
    for commit in commits:
        match = re.search(r"Ref: session_id=([\w-]+)", commit.message)
        if match:
            session_id = match.group(1)
            if session_id in sessions:
                print(f"Found match for session {session_id} in commit {commit.hexsha[:7]}")
                
                original_session = sessions[session_id]
                ground_truth_output = {"changes": []}
                
                # Use git diff-tree to find which files were changed in the commit
                changed_files = commit.tree.diff(commit.parents[0]).iter_change_type('M') # 'M' for modified

                for change in changed_files:
                    file_path = change.b_path

                    if file_path.endswith(".docx"):
                        # For Word docs, get the full text of the NEW version from the commit
                        blob_content = commit.tree[file_path].data_stream.read()
                        with tempfile.NamedTemporaryFile(delete=True, suffix=".docx") as tmp:
                            tmp.write(blob_content)
                            tmp.seek(0)
                            doc = docx.Document(tmp)
                            full_text = '\n'.join([p.text for p in doc.paragraphs])
                        ground_truth_output["changes"].append({
                            "file_path": file_path, "type": "full_document_text", "content": full_text
                        })
                    else: # For code files, get the diff
                        diff_text = repo.git.diff(commit.parents[0].hexsha, commit.hexsha, '--', file_path)
                        ground_truth_output["changes"].append({
                            "file_path": file_path, "type": "diff", "content": diff_text
                        })

                # Create the final training example
                example = {
                    "input_text": f"Business Request: {original_session['initial_request']}\nConversation History: {original_session['conversation_history']}",
                    "output_text": json.dumps(ground_truth_output)
                }
                finetuning_examples.append(example)

    print(f"\nGenerated {len(finetuning_examples)} new examples for fine-tuning.")
    
    if finetuning_examples:
        with open(FINETUNING_DATASET_FILE, 'a') as f:
            for example in finetuning_examples:
                f.write(json.dumps(example) + '\n')
        print(f"Appended examples to {FINETUNING_DATASET_FILE}")

if __name__ == "__main__":
    process_feedback_logs()