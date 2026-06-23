import os
import pandas as pd
import json
import numpy as np

# ── Project Directory Paths ──────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(BASE_DIR, "Docs")
DATA_DIR = os.path.join(BASE_DIR, "data")

# Create data directory if it doesn't exist
os.makedirs(DATA_DIR, exist_ok=True)

INPUT_FILE = os.path.join(BASE_DIR, "input", "skill_master_review_v1.xlsx")
TAXONOMY_FILE = os.path.join(DOCS_DIR, "skill_taxonomy.xlsx")
OUTPUT_FILE = os.path.join(BASE_DIR, "output", "skill_master_categorized.xlsx")

# ── Databases ────────────────────────────────────────────────────────────────
PIPELINE_STATE_DB = os.path.join(DATA_DIR, "pipeline_state.db")
WIKI_CACHE_DB = os.path.join(DATA_DIR, "wiki_cache.db")

# ── Ollama Settings ──────────────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434"
OLLAMA_EMBED_MODEL = "all-minilm"
# Default to the 3B instruct model pulled on the system for testing.
# Can be changed to "qwen2.5:7b-instruct" or any pulled model.
OLLAMA_LLM_MODEL = "hf.co/Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M"

# ── Dynamic Taxonomy Loader ──────────────────────────────────────────────────
def load_taxonomy():
    """Loads the taxonomy dynamically from Excel."""
    if not os.path.exists(TAXONOMY_FILE):
        raise FileNotFoundError(f"Taxonomy file not found at {TAXONOMY_FILE}")
    
    df = pd.read_excel(TAXONOMY_FILE, sheet_name="Skill Taxonomy")
    taxonomy = {}
    for _, row in df.iterrows():
        bucket = str(row["Skill Bucket"]).strip()
        sub_bucket = str(row["Skill Sub-Bucket"]).strip()
        if bucket and sub_bucket:
            taxonomy.setdefault(bucket, []).append(sub_bucket)
    return taxonomy

def format_taxonomy_text(taxonomy):
    """Formats the taxonomy dictionary into a string for LLM prompting."""
    lines = []
    for bucket, sub_buckets in taxonomy.items():
        lines.append(f"- {bucket}: {', '.join(sub_buckets)}")
    return "\n".join(lines)

def set_model(model_type):
    """Dynamically switch between 3b and 7b models and output file destinations."""
    global OLLAMA_LLM_MODEL, OUTPUT_FILE
    if model_type == "7b":
        OLLAMA_LLM_MODEL = "hf.co/MaziyarPanahi/Qwen2.5-7B-Instruct-GGUF:Q5_K_M"
        OUTPUT_FILE = os.path.join(BASE_DIR, "output", "skill_master_categorized_7b.xlsx")
    elif model_type == "3b":
        OLLAMA_LLM_MODEL = "hf.co/Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M"
        OUTPUT_FILE = os.path.join(BASE_DIR, "output", "skill_master_categorized_3b.xlsx")
    else:
        # Default or fallback
        OLLAMA_LLM_MODEL = "hf.co/Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M"
        OUTPUT_FILE = os.path.join(BASE_DIR, "output", "skill_master_categorized.xlsx")
    print(f"Config: Switched LLM model to '{OLLAMA_LLM_MODEL}', Output file to '{OUTPUT_FILE}'")

def get_embedding(text):
    """Fetches a single embedding vector from Ollama's local HTTP API."""
    import requests
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
            timeout=15
        )
        if r.status_code == 200:
            return r.json().get("embedding", [])
    except Exception as e:
        print(f"Config Warning: Failed to fetch embedding for '{text}': {e}")
    return []

TAXONOMY_EMBEDDINGS = None

def get_taxonomy_embeddings():
    """Lazily loads/generates and caches taxonomy sub-bucket embeddings."""
    global TAXONOMY_EMBEDDINGS
    if TAXONOMY_EMBEDDINGS is not None:
        return TAXONOMY_EMBEDDINGS

    cache_path = os.path.join(DATA_DIR, "taxonomy_embeddings_cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                raw_cache = json.load(f)
            TAXONOMY_EMBEDDINGS = {k: np.array(v) for k, v in raw_cache.items()}
            return TAXONOMY_EMBEDDINGS
        except Exception as e:
            print(f"Config Warning: Failed to load taxonomy embeddings cache: {e}")

    # Build unique list of sub-buckets from SUB_TO_BUCKET keys
    sub_buckets = sorted(list(SUB_TO_BUCKET.keys()))
    TAXONOMY_EMBEDDINGS = {}
    raw_to_save = {}
    
    print(f"Config: Pre-generating embeddings for {len(sub_buckets)} taxonomy sub-buckets...")
    for sub in sub_buckets:
        vector = get_embedding(sub)
        if len(vector) == 384:
            arr = np.array(vector)
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            TAXONOMY_EMBEDDINGS[sub] = arr
            raw_to_save[sub] = arr.tolist()
            
    # Save cache
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(raw_to_save, f, indent=2)
    except Exception as e:
        print(f"Config Warning: Failed to save taxonomy embeddings cache: {e}")
        
    return TAXONOMY_EMBEDDINGS

# Load at import time
SKILL_TAXONOMY = {}
SUB_TO_BUCKET = {}
TAXONOMY_TEXT = ""

def init_taxonomy():
    global SKILL_TAXONOMY, SUB_TO_BUCKET, TAXONOMY_TEXT
    try:
        SKILL_TAXONOMY = load_taxonomy()
        # Dynamically inject Noise / Not a Skill bucket
        SKILL_TAXONOMY["Noise / Not a Skill"] = ["Noise / Not a Skill"]
        TAXONOMY_TEXT = format_taxonomy_text(SKILL_TAXONOMY)
        # Populate sub-bucket to bucket mapping
        SUB_TO_BUCKET = {}
        for bucket, subs in SKILL_TAXONOMY.items():
            for sub in subs:
                SUB_TO_BUCKET.setdefault(sub, []).append(bucket)
    except Exception as e:
        print(f"Config Warning: Failed to initialize taxonomy: {e}")

init_taxonomy()
