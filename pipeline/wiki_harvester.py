import requests
import time
from tenacity import retry, stop_after_attempt, wait_exponential
from pipeline.config import OLLAMA_URL
from pipeline.db import (
    get_pending_wiki_skills,
    check_wiki_cache,
    save_wiki_extracts
)

# Polite bot User-Agent identifier
HEADERS = {
    "User-Agent": "SkillTaxonomyCategorizer/1.0 (nipun.kumar@example.com)"
}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_wiki_api_with_retry(params):
    """Executes a Wikipedia query API call with exponential backoff retries."""
    r = requests.get("https://en.wikipedia.org/w/api.php", params=params, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()

def fetch_search_fallback(name):
    """
    Search Wikipedia for the term if direct batch query fails,
    resolving the closest match and its description.
    """
    try:
        # Step 1: Search for the title
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": name,
            "srlimit": 1,
            "format": "json"
        }
        search_data = _call_wiki_api_with_retry(search_params)
        hits = search_data.get("query", {}).get("search", [])
        if not hits:
            return "", ""

        best_title = hits[0]["title"]

        # Step 2: Fetch extract for the best hit
        extract_params = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "exchars": 400,
            "titles": best_title
        }
        extract_data = _call_wiki_api_with_retry(extract_params)
        pages = extract_data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if int(page_id) >= 0 and "missing" not in page:
                return best_title, page.get("extract", "")[:400]
    except Exception:
        pass
    return "", ""

def run_wiki_harvester(limit=None):
    """
    Librarian Agent (Context Harvester)
    Fetches Wikipedia summaries for pending skills, batching requests
    and checking/updating the persistent cache.
    """
    print("Librarian Agent: Checking for pending context harvesting...")
    pending = get_pending_wiki_skills()
    if not pending:
        print("Librarian Agent: No pending skills to harvest.")
        return 0, 0

    if limit is not None:
        pending = pending[:limit]
        print(f"Librarian Agent: Limit set, processing {len(pending)} skills.")
    else:
        print(f"Librarian Agent: Total of {len(pending)} pending skills to process.")

    names = [s["name"] for s in pending]

    # Check cache first
    print("Librarian Agent: Querying local wiki cache...")
    cached = check_wiki_cache(names)
    print(f"Librarian Agent: Found {len(cached)} cached entries.")

    # Process cached records immediately
    if cached:
        cached_updates = []
        for name in names:
            if name in cached:
                cached_updates.append((
                    cached[name]["resolved_title"],
                    cached[name]["extract"],
                    name
                ))
        # Batch write cached statuses back to state tracking
        save_wiki_extracts([], cached_updates)
        print("Librarian Agent: Updated state for cached items.")

    # Find which skills need network fetching
    uncached_names = [name for name in names if name not in cached]
    if not uncached_names:
        print("Librarian Agent Finished: All requested items loaded from cache.")
        return len(names), 0

    print(f"Librarian Agent: Crawling Wikipedia for {len(uncached_names)} uncached skills in batches of 50...")
    
    network_fetched_count = 0
    batch_size = 50

    for i in range(0, len(uncached_names), batch_size):
        batch = uncached_names[i:i+batch_size]
        print(f"  [{i+1}-{min(i+batch_size, len(uncached_names))}/{len(uncached_names)}] Fetching batch...")
        
        # Build API Batch URL parameters
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "exchars": 400,
            "redirects": 1,
            "titles": "|".join(batch)
        }

        extracts_to_cache = []
        skill_updates_state = []

        try:
            data = _call_wiki_api_with_retry(params)
            
            # Map query titles to normalized/redirected target titles
            mapping = {t: t for t in batch}
            
            for item in data.get("query", {}).get("normalized", []):
                mapping[item["from"]] = item["to"]
                
            for item in data.get("query", {}).get("redirects", []):
                for k, v in mapping.items():
                    if v == item["from"]:
                        mapping[k] = item["to"]

            # Parse extracted pages
            page_extracts = {}
            for page_id, page in data.get("query", {}).get("pages", {}).items():
                title = page.get("title")
                if int(page_id) >= 0 and "missing" not in page:
                    page_extracts[title] = page.get("extract", "")[:400]

            # Assign extracts
            for name in batch:
                resolved_title = mapping.get(name)
                extract = page_extracts.get(resolved_title, "")

                # Fallback search if batch query missed
                if not extract:
                    resolved_title, extract = fetch_search_fallback(name)

                extracts_to_cache.append((name, resolved_title, extract))
                skill_updates_state.append((resolved_title, extract, name))

            # Commit batch results to cache and state database
            save_wiki_extracts(extracts_to_cache, skill_updates_state)
            network_fetched_count += len(batch)
            
        except Exception as e:
            print(f"  Librarian Agent Error on batch {batch[:3]}...: {e}")
            continue

        # Strict polite sleep between batches
        time.sleep(1.5)

    print(f"Librarian Agent Finished: Fetched {network_fetched_count} entries from Wikipedia API.")
    return len(names), network_fetched_count
