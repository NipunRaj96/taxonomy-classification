import numpy as np
from sklearn.cluster import Birch
from rapidfuzz import fuzz
from concurrent.futures import ThreadPoolExecutor
import pipeline.config as config
from pipeline.db import (
    get_valid_skills_for_clustering,
    save_cluster_assignments
)

def _fetch_embedding_from_ollama(text):
    """Fetches a single embedding vector using config's get_embedding."""
    return config.get_embedding(text)

def run_clusterer():
    """
    Architect Agent (Semantic Grouping & Deduplication)
    Loads valid skills, calls Ollama embeddings in parallel,
    runs Birch clustering, refines with RapidFuzz edit distance,
    and updates SQLite state.
    """
    print("Architect Agent: Loading skills for clustering...")
    skills = get_valid_skills_for_clustering()
    if not skills:
        print("Architect Agent: No valid skills found to cluster.")
        return 0, 0

    print(f"Architect Agent: Fetching embeddings for {len(skills)} skills...")
    names = [s["name"] for s in skills]
    global_ids = [s["global_id"] for s in skills]
    user_counts = [s["users"] for s in skills]

    # Parallel embedding generation via Ollama (10 concurrent threads)
    with ThreadPoolExecutor(max_workers=10) as executor:
        emb_results = list(executor.map(_fetch_embedding_from_ollama, names))

    # Keep only skills with valid embedding output
    valid_indices = [i for i, emb in enumerate(emb_results) if len(emb) == 384]
    if not valid_indices:
        print("Architect Agent Error: Failed to generate any valid embeddings.")
        return 0, 0

    filtered_skills = [skills[i] for i in valid_indices]
    filtered_names = [names[i] for i in valid_indices]
    filtered_global_ids = [global_ids[i] for i in valid_indices]
    filtered_user_counts = [user_counts[i] for i in valid_indices]
    
    embeddings = np.array([emb_results[i] for i in valid_indices])

    # L2 normalize embeddings for cosine similarity dot-product equivalence
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.where(norms == 0, 1, norms)

    print(f"Architect Agent: Running Birch clustering on {len(embeddings)} skills...")
    # threshold=0.547 is equivalent to a cosine similarity threshold of 0.85
    birch = Birch(threshold=0.547, n_clusters=None)
    birch.fit(embeddings)
    labels = birch.labels_
    print(f"Architect Agent: Birch grouped skills into {len(set(labels))} raw clusters.")

    # Group skill indices by their Birch labels
    initial_clusters = {}
    for idx, label in enumerate(labels):
        initial_clusters.setdefault(label, []).append(idx)

    print("Architect Agent: Refining clusters with RapidFuzz (85% ratio)...")
    final_assignments = []
    cluster_id_counter = 0

    for label, idxs in initial_clusters.items():
        if len(idxs) == 1:
            # Single-element cluster
            idx = idxs[0]
            final_assignments.append((cluster_id_counter, 1, filtered_global_ids[idx]))
            cluster_id_counter += 1
            continue

        # Pick representative (highest user count)
        rep_idx = max(idxs, key=lambda i: filtered_user_counts[i])
        rep_name = filtered_names[rep_idx]
        rep_gid = filtered_global_ids[rep_idx]

        valid_members = [rep_idx]
        split_idxs = []

        for idx in idxs:
            if idx == rep_idx:
                continue
            
            member_name = filtered_names[idx]
            # Compute string edit distance similarity
            str_sim = fuzz.ratio(rep_name.lower(), member_name.lower())

            # If the string similarity is high (>= 85%), keep them grouped
            if str_sim >= 85:
                valid_members.append(idx)
            else:
                split_idxs.append(idx)

        # Assign the final refined cluster ID to all valid members
        for idx in valid_members:
            is_rep = 1 if idx == rep_idx else 0
            final_assignments.append((cluster_id_counter, is_rep, filtered_global_ids[idx]))
        cluster_id_counter += 1

        # Each split member becomes its own independent single-element cluster
        for idx in split_idxs:
            final_assignments.append((cluster_id_counter, 1, filtered_global_ids[idx]))
            cluster_id_counter += 1

    # Save cluster mappings to SQLite
    save_cluster_assignments(final_assignments)
    
    unique_llm_count = sum(1 for item in final_assignments if item[1] == 1)
    reduction = ((len(filtered_skills) - unique_llm_count) / len(filtered_skills)) * 100

    print(f"Architect Agent Finished: Grouped {len(filtered_skills)} skills into {cluster_id_counter} clusters. "
          f"Representative skills to run via Ollama: {unique_llm_count} (Reduces LLM workload by {reduction:.1f}%).")
    
    return len(filtered_skills), unique_llm_count
