# Robust Skill Categorization & Summarization Pipeline (42k Scale)

This project is a high-performance, cost-free, and local pipeline designed to clean, group, categorize, and summarize **42,410 unique skills** into a predefined taxonomy.

---

## Project Overview

The taxonomy team has a master dataset of 42,410 unique skills extracted from candidate profiles and resumes. The goal is to classify each skill into a `Skill Bucket` and `Skill Sub-Bucket` using the official taxonomy, and generate a concise **one-liner summary** for each skill.

This project implements a **zero-cost, local-first architecture** optimized for a standard laptop CPU (Dell Latitude 3420, 4 Cores, 8 Threads) by incorporating:
* **Multi-Stage Noise Filtering:** Separating junk data, typos, and company names from professional and soft skills.
* **Semantic Clustering:** Grouping near-duplicates and variations using local sentence embeddings to reduce LLM calls by 70–80%.
* **Polite Wikipedia Harvesting:** Caching Wikipedia descriptions locally using API batching and polite query rates to respect Wikipedia's usage guidelines.
* **Local LLM Execution:** Leveraging Ollama with high-accuracy, instruction-tuned models optimized for CPU inference.
* **State Checkpointing:** Resuming execution from where it left off using a local SQLite state database.

---

## Architectural Details & Response to Feedback

Based on the feedback received on the initial proposal, the architecture has been refined to address the following:

### 1. Safe & Polite Wikipedia Harvesting
* **User Feedback:** *Use a proper User-Agent, avoid rapid requests, batch queries using `titles` separated by `|`, and use retry libraries.*
* **Implementation Plan:**
  * **API Batching:** Before fetching detailed extracts, the pipeline queries the Wikipedia API in batches of **50 titles** at a time using `action=query&titles=A|B|C` to check page existence and handle redirects.
  * **Polite Crawling:** The crawler uses a strict rate limiter (e.g. 1.0–2.0 second sleep between request batches).
  * **User-Agent:** Every request sends a custom header identifying the bot (`SkillTaxonomyCategorizer/1.0; nipun.kumar@example.com`).
  * **Retries & Error Handling:** Integrates `tenacity` to retry transient network errors with exponential backoff.
  * **Caching:** All successful fetches are stored in a local `wiki_cache.db` SQLite database to guarantee we never query the same skill twice.

### 2. High-Accuracy Noise Classification
* **User Feedback:** *How to classify noise vs. skill while being 100% correct, maintaining perfect accuracy?*
* **Implementation Plan:**
  * To guarantee **100% correctness**, we do not delete or drop any data automatically.
  * Instead, suspicious terms (e.g. single letters other than `C`/`R`, pure unit symbols, specific corporate names like *Dun & Bradstreet*) are categorized under a dedicated bucket: **`"Noise / Not a Skill"`**.
  * Any term with `users = 0` and `status = 3` that lacks a Wikipedia entry is flagged for human review in a specific status column (`requires_review = 1`).
  * This allows the taxonomy team to verify and bulk-approve or reject the flagged items in Excel, maintaining absolute data integrity.

### 3. Local Hardware Configuration (Dell Latitude 3420 CPU)
* **User Feedback:** *Running on 4 cores / 8 threads CPU. Cannot rely on paid APIs. Time is not a major issue (can run overnight).*
* **Implementation Plan:**
  * **Embeddings:** We use the local `sentence-transformers/all-MiniLM-L6-v2` model. This is a very lightweight (120MB) embedding model that runs extremely fast on CPU (generating embeddings for 42k skills in under 10 minutes).
  * **Ollama Model Choice:**
    * **`qwen2.5:7b-instruct` (Recommended for overnight run):** Currently the best 7B model for JSON formatting and taxonomy matching. It will run at ~2–3 tokens/sec on CPU. By clustering similar skills, we reduce the total LLM calls from 42,000 to ~6,000 unique records. 6,000 records will finish running overnight (~15–18 hours).
    * **`qwen2.5:3b-instruct` or `llama3.2:3b-instruct` (Recommended for faster testing):** A 3B parameter model runs 2-3x faster on a laptop CPU and maintains ~90% of the accuracy of the 7B model. We will use this model for development and pilot runs.

### 4. Pilot Testing (Cost = $0)
* **User Feedback:** *Test the build on a 5-10k unique record sample first to verify 100% accuracy before scaling.*
* **Implementation Plan:**
  * The execution script includes a `--sample-size` flag.
  * We will run the initial run on a sample of **5,000 unique, clustered records** (which represents the most frequent and diverse skills in the dataset).
  * The resulting Excel sheet can be audited by the taxonomy team to verify categorization logic, prompt formatting, and one-liner summaries.

### 5. Soft Skills & Corporate Entities
* **User Feedback:** *Group soft skills under a category, and treat corporate entities (e.g., Dun & Bradstreet) as noise.*
* **Implementation Plan:**
  * Soft skills will map to the existing taxonomy bucket: **`"Professional & Interpersonal Skills"`** (e.g. *Communication*, *Critical Thinking*, *Time Management*).
  * Corporate names, products not representing general professional skills, and garbage strings will be classified into the **`"Noise / Not a Skill"`** bucket.

---

## Project Structure

```
taxonomy/
│
├── README.md                          # Project documentation and architectural overview
├── agents.md                          # Multi-agent worker architecture description
│
├── categorize_skills_llama.py         # Original prototype script (reference)
├── skill_master_review_v1.xlsx        # Raw input dataset (42,410 rows)
├── skill_taxonomy.xlsx                # Official taxonomy definition
│
├── pipeline/                          # Modular implementation files
│   ├── __init__.py
│   ├── config.py                      # Pipeline configuration & model definitions
│   ├── db.py                          # SQLite cache & state management
│   ├── noise_filter.py                # String cleaning and rule-based noise detection
│   ├── wiki_harvester.py              # Batch Wikipedia API crawler with tenacity retries
│   ├── clusterer.py                   # Sentence embeddings and semantic clustering
│   └── llm_worker.py                  # Ollama local inference & structured JSON generator
│
├── run_pipeline.py                    # Main pipeline orchestrator script
│
└── data/                              # Cache files and output logs (gitignored)
    ├── wiki_cache.db                  # Local database caching Wikipedia extracts
    ├── pipeline_state.db              # SQLite checkpoint database tracking processing status
    └── skill_master_categorized.xlsx  # Final processed Excel sheet
```
