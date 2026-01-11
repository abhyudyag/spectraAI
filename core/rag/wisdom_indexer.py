import json
import chromadb
import os
from sentence_transformers import SentenceTransformer

# --- CONFIGURATION ---
DATASET_PATH = "finetuning_dataset.jsonl"
CHROMA_DB_PATH = "./claroDR"
COLLECTION_NAME = "solvo_wisdom" # Separate collection for examples
EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'
MODEL_CACHE_PATH = './.model_cache'

def index_wisdom():
    if not os.path.exists(DATASET_PATH):
        print(f"🚨 No dataset found at {DATASET_PATH}. Run feedback_processor.py first.")
        return

    print(f"Loading embedding model...")
    abs_cache_path = os.path.abspath(MODEL_CACHE_PATH)
    model = SentenceTransformer(EMBEDDING_MODEL_NAME, cache_folder=abs_cache_path)

    print(f"Initializing ChromaDB collection '{COLLECTION_NAME}'...")
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    # Delete and recreate to ensure freshness
    try:
        client.delete_collection(COLLECTION_NAME)
    except:
        pass
    collection = client.create_collection(name=COLLECTION_NAME)

    documents = []
    metadatas = []
    ids = []
    
    print("Reading dataset...")
    with open(DATASET_PATH, 'r') as f:
        for i, line in enumerate(f):
            try:
                data = json.loads(line)
                # The "input" (request) is what we search against
                input_text = data.get("input_text", "")
                # The "output" (perfect solution) is what we want to retrieve as an example
                output_text = data.get("output_text", "")
                
                # Combine them into a formatted example string
                full_example = f"Example Input:\n{input_text}\n\nExample Output:\n{output_text}"
                
                documents.append(full_example)
                metadatas.append({"source": "finetuning_dataset", "id": i})
                ids.append(f"example_{i}")
            except json.JSONDecodeError:
                continue

    if documents:
        print(f"Embedding and indexing {len(documents)} examples...")
        embeddings = model.encode(documents)
        collection.add(
            embeddings=embeddings.tolist(),
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print("✅ Wisdom indexing complete.")
    else:
        print("⚠️ No valid examples found to index.")

if __name__ == "__main__":
    index_wisdom()