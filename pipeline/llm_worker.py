import json
import re
import requests
import pipeline.config as config
from pipeline.db import (
    get_pending_representative_skills,
    save_llm_result
)

def _build_prompt(name, context, related):
    """Constructs the classification and summary prompt for Ollama."""
    related_str = ", ".join(related) if related else "None"
    return f"""You are a professional skill taxonomy expert. Categorize the skill name below into exactly one Skill Bucket and one Skill Sub-Bucket from the predefined taxonomy, and generate a highly informative one-liner summary explaining what it is.

Taxonomy (Bucket -> Sub-Buckets):
{config.TAXONOMY_TEXT}

Rules:
1. Pick the single best-fitting Bucket and Sub-Bucket from the listed taxonomy. You MUST select EXACTLY from the listed taxonomy. Do NOT invent, generalize, or hallucinate new bucket or sub-bucket names. Strict compliance with the provided taxonomy list is mandatory.
2. If the skill is NOT a professional skill or soft skill (e.g. it is a company name, a country, a product name that is not a skill, an academic degree/qualification like "Hons", "MBA", "B.Tech", a random abbreviation, or gibberish), you MUST classify it into the bucket "Noise / Not a Skill" and the sub-bucket "Noise / Not a Skill".
3. Do not copy the Wikipedia context verbatim. Instead, synthesize the Wikipedia context and related terms to write a highly informative, professional one-liner explanation of the skill. Focus on explaining its core purpose, technology stack context (if applicable), and industry usage so it is directly actionable for the taxonomy team. If it is noise, the summary should explain why (e.g., "A corporate business entity" or "Generic term").
4. Return ONLY a raw JSON object with exactly three keys: "skill_bucket", "skill_sub_bucket", and "summary". Do not include any markdown formatting, explanations, or backticks in the response.

Example output:
{{
  "skill_bucket": "Programming & Development",
  "skill_sub_bucket": "Programming Languages",
  "summary": "A high-level, general-purpose programming language known for readability and a vast ecosystem."
}}

Now, categorize this specific skill:
Skill Name: {name}
Wikipedia Context: {context or "No additional context available."}
Related terms found in candidate profiles: {related_str}
"""

def _call_ollama_json(prompt):
    """Calls Ollama in native JSON mode to generate structured outputs."""
    payload = {
        "model": config.OLLAMA_LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0}
    }
    r = requests.post(f"{config.OLLAMA_URL}/api/generate", json=payload, timeout=300)
    r.raise_for_status()
    text = r.json()["response"].strip()
    
    # Clean markdown codeblocks if Ollama wraps JSON in them
    text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)

def run_llm_worker(limit=None):
    """
    Expert Agent (LLM Categorizer & Summarizer)
    Processes representative skills pending categorization via Ollama,
    extracting bucket, sub-bucket, and a one-liner summary.
    """
    print(f"Expert Agent: Checking for representative skills to categorize (Model: {config.OLLAMA_LLM_MODEL})...")
    pending = get_pending_representative_skills()
    if not pending:
        print("Expert Agent: No pending representative skills to process.")
        return 0

    if limit is not None:
        pending = pending[:limit]
        print(f"Expert Agent: Limit set, processing {len(pending)} skills.")
    else:
        print(f"Expert Agent: Total of {len(pending)} pending representative skills to process.")

    # Warm up model to prevent initial cold-start timeouts
    print(f"Expert Agent: Warming up model '{config.OLLAMA_LLM_MODEL}' (this may take up to 90 seconds on cold start)...")
    try:
        requests.post(
            f"{config.OLLAMA_URL}/api/generate",
            json={"model": config.OLLAMA_LLM_MODEL, "prompt": "warmup", "stream": False},
            timeout=300
        )
        print("Expert Agent: Warm-up complete.")
    except Exception as e:
        print(f"Expert Agent Warning: Warm-up request timed out or failed: {e}")

    success_count = 0

    for idx, skill in enumerate(pending):
        name = skill["name"]
        gid = skill["global_id"]
        context = skill["wiki_extract"]
        
        # Load related terms
        related = []
        for key in ["top_1", "top_2", "top_3", "top_4", "top_5"]:
            if skill[key]:
                related.append(skill[key])

        print(f"  [{idx+1}/{len(pending)}] Categorizing '{name}' ...", end="", flush=True)

        prompt = _build_prompt(name, context, related)
        
        try:
            result = _call_ollama_json(prompt)
            bucket = result.get("skill_bucket", "Unknown").strip()
            sub_bucket = result.get("skill_sub_bucket", "Unknown").strip()
            summary = result.get("summary", "").strip()

            save_llm_result(gid, bucket, sub_bucket, summary)
            print(f" -> {bucket} | {sub_bucket}")
            success_count += 1
            
            # Real-time incremental audit and export to Excel
            try:
                from pipeline.auditor import run_auditor
                run_auditor()
            except Exception as ae:
                print(f"    Expert Agent Warning: Real-time audit update failed: {ae}")

        except Exception as e:
            print(f" -> ERROR: {e}")
            # Save fallback to prevent blocking future steps
            save_llm_result(gid, "Unknown", "Unknown", f"Error generating summary: {e}")
            try:
                from pipeline.auditor import run_auditor
                run_auditor()
            except Exception:
                pass

    print(f"Expert Agent Finished: Categorized {success_count} representative skills.")
    return success_count
