import os
import json
import chromadb
from unstructured.partition.html import partition_html
import sys
import time
from collections import Counter
from sentence_transformers import SentenceTransformer
from .chunker import chunk_code_by_functions
import subprocess
import tempfile
import shutil
from atlassian import Confluence
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import urllib3

# --- Suppress InsecureRequestWarning ---
# We are intentionally disabling SSL verification for internal sites,
# so we can safely disable the warning.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# --- Constants ---
os.environ['TRANSFORMERS_OFFLINE'] = '1'
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
MODEL_CACHE_PATH = os.path.join(PROJECT_ROOT, 'data', 'model_cache')
VECTOR_DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'vector_store')
CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, 'config', 'indexer_config.json')

# --- CONFIGURATION MANAGEMENT ---

def load_config(config_path):
    """Loads the JSON config file if it exists."""
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"🚨 ERROR: Could not read or parse config file. Error: {e}")
            return {}
    return {}

def save_config(config_data, config_path):
    """Saves the configuration data to the JSON file."""
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(config_data, f, indent=2)
        print(f"✅ Configuration saved to {config_path}")
    except IOError as e:
        print(f"🚨 ERROR: Could not save config file. Error: {e}")

def get_user_config(config_path):
    """
    Deprecated: Use interfaces/cli/indexer_cli.py for interactive configuration.
    This function remains for backward compatibility but raises a warning.
    """
    print("⚠️ Warning: core.rag.indexer.get_user_config is deprecated. Use interfaces.cli.indexer_cli instead.")
    return load_config(config_path), "both" # Default fallback


# --- DATA FETCHING ---

def setup_codebase(config):
    """Clones a git repo if necessary and returns the path to the code."""
    if config.get('source_type') == "local":
        return config.get('codebase_path'), None
    elif config.get('source_type') == "git":
        cloned_path = os.path.join(tempfile.gettempdir(), "keystone_cloned_repo")
        if os.path.exists(cloned_path):
            shutil.rmtree(cloned_path)
        try:
            subprocess.run(["git", "clone", "--depth", "1", config['git_url'], cloned_path], check=True, capture_output=True, text=True)
            return cloned_path, cloned_path
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"🚨 Git clone failed. Error: {e}")
            return None, None
    return None, None

def fetch_confluence_documents_via_scraping(conf_config):
    """
    Crawls and scrapes Confluence pages starting from a list of URLs.
    """
    documents = []
    start_urls = conf_config.get('start_urls', [])
    base_url = conf_config.get('base_url')
    
    urls_to_visit = list(start_urls)
    visited_urls = set()

    print(f"\nCrawling Confluence content from {len(urls_to_visit)} starting URL(s)...")

    while urls_to_visit:
        url = urls_to_visit.pop(0)
        if url in visited_urls:
            continue
        
        visited_urls.add(url)
        print(f"  - Scraping: {url}")

        try:
            response = requests.get(url, verify=False)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            
            main_content = soup.find(id='main-content')
            if main_content:
                html_content = str(main_content)
                elements = partition_html(text=html_content)
                clean_content = "\n\n".join([el.text for el in elements if el.text.strip()])
                title = soup.find('title').string if soup.find('title') else "Untitled"
                documents.append({"content": clean_content, "metadata": {"source": url, "title": title}})
            else:
                print(f"    - WARNING: Could not find main content for page: {url}.")

            children_list = soup.select_one('ul.page-tree-list')
            if children_list:
                child_links = children_list.find_all('a', href=True)
                for link in child_links:
                    href = link['href']
                    full_url = urlparse.urljoin(base_url, href)
                    if full_url not in visited_urls:
                        urls_to_visit.append(full_url)
                        print(f"    - Discovered child page: {full_url}")

        except requests.exceptions.RequestException as e:
            print(f"    - 🚨 ERROR: Failed to fetch URL {url}. Error: {e}")
    
    print(f"✅ Crawled and processed {len(documents)} total pages.")
    return documents

def fetch_confluence_documents_via_api(conf_config):
    """
    Fetches Confluence pages using the Atlassian API.
    """
    documents = []
    base_url = conf_config.get('base_url')
    username = conf_config.get('username')
    api_token = conf_config.get('api_token')

    # Normalize Base URL (remove /display/... or similar paths)
    parsed_url = urlparse(base_url)
    clean_base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    # Keep standard path if it exists (e.g. /wiki), but usually just scheme+netloc is safest for root
    # If the user entered a deep link, we strip it.
    if parsed_url.path and parsed_url.path != '/' and not parsed_url.path.startswith('/wiki'):
         print(f"ℹ️  Adjusting Confluence URL from {base_url} to {clean_base_url}")
         base_url = clean_base_url

    try:
        # Determine Auth Method
        is_cloud = 'atlassian.net' in base_url
        
        if is_cloud:
            # Cloud uses Email + API Token
            confluence = Confluence(
                url=base_url,
                username=username,
                password=api_token,
                cloud=True
            )
        else:
            # Server/Data Center
            # Try to use token as PAT if available, otherwise fallback to Basic Auth
            if api_token and not username:
                confluence = Confluence(
                    url=base_url,
                    token=api_token,
                    verify_ssl=False
                )
            elif api_token: 
                # If both provided on Server, it's ambiguous. 
                # If "api_token" is actually a password, use Basic Auth.
                # If it's a PAT, prefer 'token' param.
                # Given the user prompt said "API Token", let's try PAT first if length is long enough?
                # Or just try one then the other?
                # Let's default to treating it as a PAT if it looks like one (usually long alphanumeric)
                # But to be safe, let's try PAT first.
                try:
                    # Attempt connection with PAT
                    confluence = Confluence(url=base_url, token=api_token, verify_ssl=False)
                    # Verify by making a cheap call
                    confluence.get_all_spaces(start=0, limit=1) # Safer check than get_space
                except Exception as e:
                    # Fallback to Basic Auth
                    print(f"ℹ️  PAT authentication failed: {e}. Trying Basic Auth...")
                    confluence = Confluence(
                        url=base_url,
                        username=username,
                        password=api_token,
                        verify_ssl=False
                    )
            else:
                 # Just Basic Auth
                 confluence = Confluence(
                    url=base_url,
                    username=username,
                    password=api_token,
                    verify_ssl=False
                )
        
        space_key = input("Enter Confluence Space Key to index: ").strip()
        
        if not space_key:
            print("No space key provided. Aborting API fetch.")
            return []

        print(f"Fetching pages from space: {space_key}...")
        
        start = 0
        limit = 50
        while True:
            pages = confluence.get_all_pages_from_space(space_key, start=start, limit=limit, expand='body.storage')
            if not pages:
                break
                
            for page in pages:
                page_id = page.get('id')
                title = page.get('title')
                body = page.get('body', {}).get('storage', {}).get('value', '')
                
                # Basic cleaning of HTML body
                if body:
                    # Using partition_html to clean text similar to scraping method
                    elements = partition_html(text=body)
                    clean_content = "\n\n".join([el.text for el in elements if el.text.strip()])
                    
                    documents.append({
                        "content": clean_content,
                        "metadata": {
                            "source": f"{base_url}/pages/viewpage.action?pageId={page_id}",
                            "title": title,
                            "id": page_id
                        }
                    })
            
            start += limit
            print(f"  - Processed {len(documents)} pages so far...")

    except Exception as e:
        print(f"🚨 Confluence API Error: {e}")
        return []

    print(f"✅ API fetch complete. Processed {len(documents)} total pages.")
    return documents

def fetch_confluence_documents(config):
    """
    Main dispatcher for fetching Confluence documents.
    Decides whether to use the API or web scraping based on config.
    """
    conf_config = config.get('confluence_config', {})
    base_url = conf_config.get('base_url')
    if not base_url:
        return []

    parsed_url = urlparse(base_url)
    confluence_host = parsed_url.hostname
    if confluence_host:
        no_proxy_val = os.environ.get("NO_PROXY", "")
        if confluence_host not in no_proxy_val:
            os.environ["NO_PROXY"] = f"{no_proxy_val},{confluence_host}"
            os.environ["no_proxy"] = os.environ["NO_PROXY"]
            print(f"Bypassing proxy for host: {confluence_host}")

    if conf_config.get('username') and conf_config.get('api_token'):
        return fetch_confluence_documents_via_api(conf_config)
    else:
        return fetch_confluence_documents_via_scraping(conf_config)


def process_codebase_generator(codebase_path, blacklisted_extensions, ignored_dirs, start_id_counter, batch_size=1000):
    """
    Generator that yields batches of chunks from the codebase.
    This prevents loading the entire codebase into memory at once.
    """
    chunk_texts = []
    chunk_metadatas = []
    chunk_ids = []
    chunk_id_counter = start_id_counter
    
    # --- IGNORE LISTS ---
    BLACKLISTED_EXTENSIONS = set(blacklisted_extensions)
    IGNORED_DIRS = set(ignored_dirs)
    print(f"Scanning codebase: {codebase_path}")
    print("DEBUG: Starting directory walk (Streaming Mode)...") 
    
    file_count = 0

    for root, dirs, files in os.walk(codebase_path):
        # Prune ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        
        for file in files:
            file_path = os.path.join(root, file)
            _, ext = os.path.splitext(file)
            ext_lower = ext.lower()
            
            if ext_lower in BLACKLISTED_EXTENSIONS: continue
            
            # Determine language
            language = "java" 
            if ext_lower == ".py": language = "python"
            elif ext_lower in [".c", ".h", ".cpp", ".hpp", ".cc"]: language = "c"
            elif ext_lower in [".pc", ".ppc", ".ph"]: language = "proc"
            elif ext_lower in [".cbl", ".cob", ".pco"]: language = "cobol"
            elif ext_lower in [".sh", ".bash", ".zsh", ".ksh"]: language = "shell"
            elif ext_lower in [".md", ".txt", ".rst"]: language = "document"
            
            try:
                file_size = os.path.getsize(file_path)
                if file_size > 1 * 1024 * 1024:
                    print(f"DEBUG: Processing large file ({file_size} bytes): {file_path}")

                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                if content:
                    chunks_with_metadata = chunk_code_by_functions(file_path, content, language=language)
                    for chunk_data in chunks_with_metadata:
                        chunk_texts.append(chunk_data["text_chunk"])
                        chunk_metadatas.append(chunk_data["metadata"])
                        chunk_ids.append(f"chunk_{chunk_id_counter}")
                        chunk_id_counter += 1
                
                file_count += 1
                if file_count % 100 == 0:
                    print(f"  Processed {file_count} files...", end='\r', flush=True)

                # YIELD BATCH IF LIMIT REACHED
                if len(chunk_ids) >= batch_size:
                    yield chunk_texts, chunk_metadatas, chunk_ids
                    # Reset buffers
                    chunk_texts = []
                    chunk_metadatas = []
                    chunk_ids = []

            except Exception as e:
                if not isinstance(e, UnicodeDecodeError):
                   print(f"Skipping file {file_path} due to error: {e}")
                   
    # Yield any remaining chunks
    if chunk_ids:
        yield chunk_texts, chunk_metadatas, chunk_ids

    print(f"\n  Processed {file_count} files total.      ")


def process_codebase(codebase_path, blacklisted_extensions, ignored_dirs, start_id_counter):
    """
    DEPRECATED: Non-streaming version. Kept for backward compatibility if needed.
    """
    print("⚠️ Warning: Using deprecated non-streaming process_codebase.")
    all_texts, all_metas, all_ids = [], [], []
    generator = process_codebase_generator(codebase_path, blacklisted_extensions, ignored_dirs, start_id_counter)
    for texts, metas, ids in generator:
        all_texts.extend(texts)
        all_metas.extend(metas)
        all_ids.extend(ids)
    return all_texts, all_metas, all_ids


def upload_batch_to_chromadb(collection, embedding_model, chunk_texts, chunk_metadatas, chunk_ids):
    """
    Encodes and uploads a SINGLE batch of text.
    Used in the streaming loop.
    """
    if not chunk_texts: return

    try:
        # 1. Generate Embeddings (for just this batch)
        embeddings = embedding_model.encode(chunk_texts, show_progress_bar=False)
        
        # 2. Upload to Chroma
        max_retries = 3
        for attempt in range(max_retries):
            try:
                collection.add(
                    embeddings=embeddings.tolist(),
                    documents=chunk_texts,
                    metadatas=chunk_metadatas,
                    ids=chunk_ids
                )
                # Success
                time.sleep(0.5) # Let DB breathe
                return 
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
                else:
                    print(f"\n🚨 Failed to upload batch of {len(chunk_ids)} chunks: {e}")
                    
    except Exception as e:
        print(f"\n🚨 Critical error in batch processing: {e}")

def batch_upload_to_chromadb(collection, embedding_model, chunk_texts, chunk_metadatas, chunk_ids):
     """
     Legacy function for batch uploading pre-computed lists.
     """
     # Reuse the new single-batch uploader logic but we have to split it again here
     # because this function expects the full list.
     BATCH_SIZE = 200
     total_items = len(chunk_ids)
     print(f"Batch uploading {total_items} items...")
     
     for i in range(0, total_items, BATCH_SIZE):
         end = min(i + BATCH_SIZE, total_items)
         upload_batch_to_chromadb(
             collection, 
             embedding_model, 
             chunk_texts[i:end], 
             chunk_metadatas[i:end], 
             chunk_ids[i:end]
         )
         print(f"Processed {end}/{total_items}...", end='\r')
     print("\nUpload complete.")

# --- MAIN EXECUTION ---
# Main execution logic has been moved to interfaces/cli/indexer_cli.py