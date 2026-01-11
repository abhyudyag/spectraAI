import json
import os
import chromadb
from sentence_transformers import SentenceTransformer
from datetime import datetime

# --- CONFIGURATION ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
FEEDBACK_FILE = os.path.join(PROJECT_ROOT, 'data', 'solvo_feedback.jsonl')
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'vector_store')
WISDOM_COLLECTION = "solvo_wisdom"
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'
MODEL_CACHE = os.path.join(PROJECT_ROOT, 'data', 'model_cache')

def learn_from_feedback():
    print(f"🧠 Starting Wisdom Learning Process...")
    print(f"📂 Reading feedback from: {FEEDBACK_FILE}")

    if not os.path.exists(FEEDBACK_FILE):
        print("⚠️ No feedback file found. Waiting for pilot data.")
        return

    # 1. Initialize DB and Model
    client = chromadb.PersistentClient(path=DB_PATH)
    collection = client.get_or_create_collection(name=WISDOM_COLLECTION)
    model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=MODEL_CACHE)

    new_examples = []
    ids = []
    metadatas = []

    # 2. Filter and Process Feedback
    with open(FEEDBACK_FILE, 'r') as f:
        for i, line in enumerate(f):
            try:
                entry = json.loads(line)
                rating = entry.get("rating", 0)
                
                # CRITICAL: Only learn from high-quality interactions (4 or 5 stars)
                if rating >= 4:
                    # We reconstruct the "Golden Example"
                    # Input: The user's original request + conversation context
                    # Output: The Agent's final response (which was rated highly)
                    
                    # Extract the last user prompt (the trigger)
                    history = entry.get("conversation_history", [])
                    last_user_input = ""
                    for msg in reversed(history):
                        if msg['role'] == 'user':
                            last_user_input = msg['content']
                            break
                    
                    if not last_user_input:
                        continue # Skip if malformed

                    # The high-quality output
                    agent_output = entry.get("final_solution", {})
                    # Convert dict to string representation for the example
                    agent_output_str = json.dumps(agent_output, indent=2)

                    # Format the "Wisdom Chunk"
                    wisdom_text = f"User Request:\n{last_user_input}\n\nIdeal Output:\n{agent_output_str}"
                    
                    new_examples.append(wisdom_text)
                    
                    # Metadata for traceability
                    ids.append(f"feedback_{entry['session_id']}_{i}")
                    metadatas.append({
                        "source": "user_feedback",
                        "rating": rating,
                        "timestamp": datetime.now().isoformat(),
                        "comment": entry.get("comment", "")
                    })
            
            except json.JSONDecodeError:
                continue

    # 3. Update the Knowledge Base
    if new_examples:
        print(f"🚀 Found {len(new_examples)} high-quality examples to learn.")
        embeddings = model.encode(new_examples)
        
        collection.upsert(
            ids=ids,
            embeddings=embeddings.tolist(),
            documents=new_examples,
            metadatas=metadatas
        )
        print("✅ Wisdom Collection Updated. Solvo is now smarter.")
    else:
        print("ℹ️ No new high-quality feedback found to learn from.")

if __name__ == "__main__":
    learn_from_feedback()