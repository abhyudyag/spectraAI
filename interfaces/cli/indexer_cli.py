import os
import sys
import argparse
from sentence_transformers import SentenceTransformer
import chromadb
import shutil

# Add project root to sys.path to allow imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
sys.path.append(project_root)

from core.rag.indexer import (
    load_config, save_config, setup_codebase, 
    fetch_confluence_documents, process_codebase, 
    batch_upload_to_chromadb, 
    EMBEDDING_MODEL_NAME, MODEL_CACHE_PATH, 
    VECTOR_DB_PATH, CONFIG_FILE_PATH
)

def get_user_config_interactive(config_path):
    """
    Interactively prompts the user to get all necessary configurations,
    loading existing values from the config file first.
    """
    config = load_config(config_path)
    if not config:
        config = {"blacklisted_extensions": [], "confluence_config": {}}

    print("--- 🚀 Keystone Indexer Setup ---")
    
    index_choice = ""
    while index_choice not in ["code", "confluence", "both"]:
        index_choice = input("What do you want to index? (code / confluence / both): ").lower().strip()

    # --- Database Config ---
    if index_choice in ["code", "confluence", "both"]:
        config['db_path'] = input(f"Enter ChromaDB path for this source (default: {config.get('db_path', VECTOR_DB_PATH)}): ") or config.get('db_path', VECTOR_DB_PATH)
        config['collection_name'] = input(f"Enter collection name (default: {config.get('collection_name', 'default_collection')}): ") or config.get('collection_name', 'default_collection')

    # --- Codebase Config ---
    if index_choice in ["code", "both"]:
        source_type = ""
        while source_type not in ["local", "git"]:
            source_type = input("Is the codebase 'local' or a 'git' repo? (local/git): ").lower().strip()
        config['source_type'] = source_type

        if source_type == "local":
            while True:
                path = input(f"Enter local codebase path: ")
                if os.path.isdir(path):
                    config['codebase_path'] = path
                    break
                else:
                    print("🚨 Path not found. Please try again.")
        elif source_type == "git":
            config['git_url'] = input(f"Enter Git repository URL: ")

    # --- Confluence Config ---
    if index_choice in ["confluence", "both"]:
        conf_config = config.get('confluence_config', {})
        print("\n--- Confluence Configuration ---")
        conf_config['base_url'] = input(f"Enter Confluence Base URL (e.g., https://confluence.example.com): ") or conf_config.get('base_url')

        # Prompt for Credentials
        conf_config['username'] = input(f"Enter Confluence Username (optional): ") or conf_config.get('username')
        conf_config['api_token'] = input(f"Enter Confluence API Token (optional): ") or conf_config.get('api_token')

        if conf_config['username'] and conf_config['api_token']:
            print("✅ Confluence API credentials configured.")
            conf_config['start_urls'] = []
        else:
            print("Credentials not provided. Switching to Web Scraping mode.")
            existing_urls = conf_config.get('start_urls', [])
            
            if existing_urls:
                print("\nFound existing Confluence Start URLs:")
                for i, url in enumerate(existing_urls):
                    print(f"  {i+1}: {url}")
                
                action = ""
                while action not in ['k', 'a', 'r', 'rep']:
                    action = input("Action: (k)eep, (a)dd new, (r)emove, (rep)lace all? ").lower().strip()

                if action == 'a':
                    new_urls_str = input("Enter new URLs to add (comma-separated): ")
                    new_urls = [u.strip() for u in new_urls_str.split(',') if u.strip()]
                    existing_urls.extend(new_urls)
                elif action == 'r':
                    to_remove_str = input("Enter numbers of URLs to remove (comma-separated): ")
                    indices_to_remove = {int(i.strip()) - 1 for i in to_remove_str.split(',') if i.strip().isdigit()}
                    existing_urls = [url for i, url in enumerate(existing_urls) if i not in indices_to_remove]
                elif action == 'rep':
                    new_urls_str = input("Enter the new list of URLs (comma-separated): ")
                    existing_urls = [u.strip() for u in new_urls_str.split(',') if u.strip()]
            else:
                 print("No existing Confluence URLs found.")
                 new_urls_str = input("Enter starting Confluence Page URLs (comma-separated): ")
                 existing_urls = [u.strip() for u in new_urls_str.split(',') if u.strip()]

            conf_config['start_urls'] = sorted(list(set(existing_urls))) # Sort for consistent order
            conf_config['start_page_ids'] = []
            
        config['confluence_config'] = conf_config

    save_config(config, config_path)
    return config, index_choice

def main():
    config, index_choice = get_user_config_interactive(CONFIG_FILE_PATH)
    
    # --- Initialize services ---
    embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, cache_folder=MODEL_CACHE_PATH, local_files_only=True)
    client = chromadb.PersistentClient(path=config.get('db_path', VECTOR_DB_PATH))
    collection = client.get_or_create_collection(name=config.get('collection_name', 'default_collection'))
    
    chunk_texts, chunk_metadatas, chunk_ids = [], [], []
    chunk_id_counter = 0

    # --- 1. Process Codebase (Streaming) ---
    codebase_path, cleanup_path = None, None
    if index_choice in ["code", "both"]:
        codebase_path, cleanup_path = setup_codebase(config)
        if codebase_path:
            print(f"\nScanning codebase at: {codebase_path}")
            # Ensure ignored_dirs has sensible defaults if not in config
            ignored_dirs = config.get("ignored_dirs", [])
            if not ignored_dirs:
                ignored_dirs = [".git", "node_modules", "__pycache__", "venv", ".svn", ".hg", "CVS", ".DS_Store", "dist", "build", "target", ".idea", ".vscode", ".vs"]

            from core.rag.indexer import process_codebase_generator, upload_batch_to_chromadb

            # Use the generator directly
            chunk_generator = process_codebase_generator(
                codebase_path, 
                config.get("blacklisted_extensions", []), 
                ignored_dirs,
                chunk_id_counter,
                batch_size=1000 # Configurable batch size for processing
            )
            
            total_chunks = 0
            for batch_texts, batch_metas, batch_ids in chunk_generator:
                if batch_texts:
                    upload_batch_to_chromadb(collection, embedding_model, batch_texts, batch_metas, batch_ids)
                    total_chunks += len(batch_ids)
                    chunk_id_counter += len(batch_ids)
            
            print(f"\n✅ Indexed {total_chunks} chunks from codebase.")

    # --- 2. Process Confluence ---
    if index_choice in ["confluence", "both"]:
        documents = fetch_confluence_documents(config)
        # Process confluence docs in a simple batch since they are usually smaller
        conf_texts, conf_metas, conf_ids = [], [], []
        for doc in documents:
            conf_texts.append(doc['content'])
            conf_metas.append(doc['metadata'])
            conf_ids.append(f"chunk_{chunk_id_counter}")
            chunk_id_counter += 1
        
        if conf_texts:
             # Use the batch uploader we defined
             from core.rag.indexer import batch_upload_to_chromadb
             batch_upload_to_chromadb(collection, embedding_model, conf_texts, conf_metas, conf_ids)

    # --- Cleanup ---
    if cleanup_path and os.path.exists(cleanup_path):
        if input("Delete temporary git clone? (y/n): ").lower() == 'y':
            shutil.rmtree(cleanup_path)

    print("\nIndexing complete.")

if __name__ == "__main__":
    main()

