import chromadb
from sentence_transformers import SentenceTransformer
import os

# --- Constants ---
# Set to offline mode
os.environ['TRANSFORMERS_OFFLINE'] = '1'
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
MODEL_CACHE_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'model_cache')

class Retriever:
    def __init__(self, db_path, collection_name):
        self.db_path = db_path
        self.collection_name = collection_name
        
        try:
            self.client = chromadb.PersistentClient(path=self.db_path)
            self.collection = self.client.get_collection(name=self.collection_name)
            
            abs_cache_path = os.path.abspath(MODEL_CACHE_PATH)
            print(f"Loading local embedding model: {EMBEDDING_MODEL_NAME} from {abs_cache_path}")
            
            # Use local_files_only to prevent network calls
            self.embedding_model = SentenceTransformer(
                EMBEDDING_MODEL_NAME, 
                cache_folder=abs_cache_path,
                local_files_only=True
            )
            print("✅ Retriever initialized successfully.")
            
        except Exception as e:
            print(f"🚨 FATAL: Could not initialize retriever. DB path: '{self.db_path}'. Error: {e}")
            raise e # Re-raise the exception to halt execution

    def get_context_for_request(self, business_request, top_k=15):
        print(f"Retrieving context for: '{business_request}'")
        try:
            # 1. Semantic Search (Vector)
            query_embedding = self.embedding_model.encode(business_request)
            semantic_results = self.collection.query(
                query_embeddings=[query_embedding.tolist()],
                n_results=top_k
            )

            # 2. Keyword Search (Extract potential function names)
            # Simple heuristic: look for words in the request that look like function names (snake_case or camelCase)
            import re
            # Only match words with at least 4 chars to avoid noise
            potential_keywords = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', business_request)
            # Filter out common English words (optional, but good for noise reduction)
            common_words = {"what", "where", "when", "function", "code", "file", "does", "this", "help", "find", "show", "tell"}
            keywords = [w for w in potential_keywords if w.lower() not in common_words]
            
            keyword_docs = []
            keyword_metas = []
            
            if keywords:
                print(f"  🔎 Attempting keyword search for: {keywords}")
                for kw in keywords:
                    try:
                        kw_results = self.collection.get(
                            where_document={"$contains": kw},
                            limit=5,
                            include=["documents", "metadatas"]
                        )
                        if kw_results['ids']:
                            keyword_docs.extend(kw_results['documents'])
                            keyword_metas.extend(kw_results['metadatas'])
                    except Exception as e:
                        print(f"    Warning: Keyword search failed for '{kw}': {e}")

            # 3. Merge Results (Deduplicate)
            seen_content = set()
            final_docs = []
            final_metas = []

            # Add keyword results first (high priority)
            for doc, meta in zip(keyword_docs, keyword_metas):
                if doc not in seen_content:
                    final_docs.append(doc)
                    final_metas.append(meta)
                    seen_content.add(doc)

            # Add semantic results next
            if semantic_results['documents'] and semantic_results['documents'][0]:
                for doc, meta in zip(semantic_results['documents'][0], semantic_results['metadatas'][0]):
                     if doc not in seen_content:
                        final_docs.append(doc)
                        final_metas.append(meta)
                        seen_content.add(doc)
            
            # Trim to top_k * 1.5 to allow for a bit more context
            final_docs = final_docs[:int(top_k * 1.5)]
            final_metas = final_metas[:int(top_k * 1.5)]
            
            context_block = "# CONTEXT FROM EXISTING APPLICATION\n\n---\n"
            if not final_docs:
                print("⚠️ No relevant context found in ChromaDB.")
                return "# CONTEXT\nNo relevant context found.\n"

            print(f"✅ Retrieved {len(final_docs)} relevant chunks (Merged Semantic + Keyword). Sources:")
            for doc, metadata in zip(final_docs, final_metas):
                file_path = metadata.get('file_path', 'Unknown Path')
                print(f"   - {file_path} (Type: {metadata.get('type', 'N/A')})")
                context_block += f"### FILE: {file_path}\n```\n{doc}\n```\n---\n"

            return context_block
            
        except Exception as e:
            print(f"🚨 Error during context retrieval: {e}")
            return "# CONTEXT RETRIEVAL FAILED\n"