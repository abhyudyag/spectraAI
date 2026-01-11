import chromadb
import os
import sys

# --- Constants ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
VECTOR_DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'vector_store')

def search_db(query_text=None, filename=None):
    print(f"Connecting to ChromaDB at: {VECTOR_DB_PATH}")
    try:
        client = chromadb.PersistentClient(path=VECTOR_DB_PATH)
        # Assuming the user uses the default collection or we list them
        collections = client.list_collections()
        
        for col in collections:
            print(f"\nScanning Collection: {col.name}")
            
            # 1. Search by Filename Metadata if provided
            if filename:
                print(f"  🔎 Looking for file matching: '{filename}'...")
                # ChromaDB filtering
                results = col.get(
                    where={"file_path": {"$contains": filename}},
                    include=["metadatas"]
                )
                if results['ids']:
                    print(f"    ✅ Found {len(results['ids'])} chunks for file '{filename}'.")
                    # Print first 5 types
                    for i, meta in enumerate(results['metadatas'][:5]):
                         print(f"       - Chunk {i}: {meta.get('type')} (lines {meta.get('start_line')}-{meta.get('end_line')})")
                else:
                    print(f"    ❌ No chunks found for file '{filename}' in this collection.")

            # 2. Search by Content (Exact String Match) if provided
            # Note: This scans the DB, which is slow for huge DBs but fine for debugging
            if query_text:
                print(f"  🔎 Scanning content for text: '{query_text}'...")
                # We have to fetch all documents to do a substring search because Chroma doesn't support regex/substring on document content directly in 'where'
                # For efficiency, we'll peek or fetch in batches if needed, but let's try a simpler approach: 
                # relying on the user to provide a file path is better, but let's try to query.
                
                # Actually, Chroma's 'get' supports 'where_document' with $contains!
                results = col.get(
                    where_document={"$contains": query_text},
                    include=["metadatas", "documents"],
                    limit=5
                )
                
                if results['ids']:
                     print(f"    ✅ Found {len(results['ids'])} chunks containing '{query_text}'.")
                     for i, (doc, meta) in enumerate(zip(results['documents'], results['metadatas'])):
                         print(f"       - Match {i+1} in {meta.get('file_path')} (Type: {meta.get('type')})")
                         print(f"         Snippet: {doc[:100]}...")
                else:
                     print(f"    ❌ No chunks found containing text '{query_text}'.")

    except Exception as e:
        print(f"🚨 Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_db.py <search_term> [filename_substring]")
        print("Example: python inspect_db.py my_function_name")
        print("Example: python inspect_db.py my_function_name my_file.c")
    else:
        q = sys.argv[1]
        f = sys.argv[2] if len(sys.argv) > 2 else None
        search_db(q, f)

