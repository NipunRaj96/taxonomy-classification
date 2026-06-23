import pandas as pd
import os
from rapidfuzz import process, utils
import pipeline.config as config
from pipeline.db import get_all_skills_for_audit, save_audit_results, get_connection, PIPELINE_STATE_DB

def _fuzzy_correct_taxonomy(bucket, sub_bucket):
    """
    Validates and corrects bucket/sub-bucket names using:
    - Layer 1: Direct exact match (case/space insensitive)
    - Layer 2: Text fuzzy match (rapidfuzz ratio >= 80)
    - Layer 3: Semantic embedding match (cosine similarity >= 0.70)
    """
    if not bucket or not sub_bucket:
        return "Unknown", "Unknown"

    if bucket == "Noise / Not a Skill":
        return "Noise / Not a Skill", "Noise / Not a Skill"

    # Pre-build normalized mappings if not already cached
    # Let's normalize strings by lowercasing and stripping whitespace
    def normalize(text):
        return "".join(text.lower().split())

    # Build a lookup of valid bucket -> sub-buckets
    # and a flat list of all valid combinations
    valid_taxonomy = [] # list of (official_bucket, official_sub_bucket)
    for b_off, s_list in config.SKILL_TAXONOMY.items():
        for s_off in s_list:
            valid_taxonomy.append((b_off, s_off))

    # --- Layer 1: Direct Exact Match ---
    norm_bucket = normalize(bucket)
    norm_sub_bucket = normalize(sub_bucket)

    for b_off, s_off in valid_taxonomy:
        if normalize(b_off) == norm_bucket and normalize(s_off) == norm_sub_bucket:
            return b_off, s_off

    # --- Layer 2: Text Fuzzy Match ---
    # Try hierarchical fuzzy match first (match bucket, then sub-bucket)
    valid_buckets = list(config.SKILL_TAXONOMY.keys())
    res_bucket = process.extractOne(bucket, valid_buckets, processor=utils.default_process)
    if res_bucket and res_bucket[1] >= 80:
        matched_bucket = res_bucket[0]
        # Match sub-bucket within this matched bucket
        valid_subs = config.SKILL_TAXONOMY[matched_bucket]
        res_sub = process.extractOne(sub_bucket, valid_subs, processor=utils.default_process)
        if res_sub and res_sub[1] >= 80:
            return matched_bucket, res_sub[0]

    # Try global sub-bucket fuzzy match (match sub-bucket first, find its bucket)
    all_sub_buckets = list(config.SUB_TO_BUCKET.keys())
    res_sub_global = process.extractOne(sub_bucket, all_sub_buckets, processor=utils.default_process)
    if res_sub_global and res_sub_global[1] >= 80:
        matched_sub = res_sub_global[0]
        possible_buckets = config.SUB_TO_BUCKET[matched_sub]
        # If it's a unique sub-bucket, return it and its bucket
        if len(possible_buckets) == 1:
            return possible_buckets[0], matched_sub
        else:
            # Resolve Business Analysis
            res_b = process.extractOne(bucket, possible_buckets, processor=utils.default_process)
            if res_b and res_b[1] >= 80:
                return res_b[0], matched_sub
            return possible_buckets[0], matched_sub

    # --- Layer 3: Semantic Embedding Match ---
    # Fetch embedding of the LLM's sub-bucket output
    sub_emb = config.get_embedding(sub_bucket)
    if len(sub_emb) == 384:
        import numpy as np
        # L2 normalize
        sub_emb_arr = np.array(sub_emb)
        norm = np.linalg.norm(sub_emb_arr)
        if norm > 0:
            sub_emb_arr = sub_emb_arr / norm

        # Get taxonomy embeddings
        tax_embs = config.get_taxonomy_embeddings()
        best_sub = None
        best_sim = -1.0

        for s_tax, s_emb in tax_embs.items():
            sim = np.dot(sub_emb_arr, s_emb)
            if sim > best_sim:
                best_sim = sim
                best_sub = s_tax

        if best_sim >= 0.70:
            possible_buckets = config.SUB_TO_BUCKET[best_sub]
            if len(possible_buckets) == 1:
                print(f"    Auditor: Semantically mapped '{bucket} -> {sub_bucket}' to '{possible_buckets[0]} -> {best_sub}' (Similarity: {best_sim:.3f})")
                return possible_buckets[0], best_sub
            else:
                # Resolve Business Analysis: match the bucket semantically too
                bucket_emb = config.get_embedding(bucket)
                if len(bucket_emb) == 384:
                    bucket_emb_arr = np.array(bucket_emb)
                    b_norm = np.linalg.norm(bucket_emb_arr)
                    if b_norm > 0:
                        bucket_emb_arr = bucket_emb_arr / b_norm
                    
                    best_b_sim = -1.0
                    best_b = possible_buckets[0]
                    for b_opt in possible_buckets:
                        b_opt_emb = config.get_embedding(b_opt)
                        if len(b_opt_emb) == 384:
                            b_opt_arr = np.array(b_opt_emb)
                            b_opt_norm = np.linalg.norm(b_opt_arr)
                            if b_opt_norm > 0:
                                b_opt_arr = b_opt_arr / b_opt_norm
                            b_sim = np.dot(bucket_emb_arr, b_opt_arr)
                            if b_sim > best_b_sim:
                                best_b_sim = b_sim
                                best_b = b_opt
                    print(f"    Auditor: Semantically mapped '{bucket} -> {sub_bucket}' to '{best_b} -> {best_sub}' (Similarity: {best_sim:.3f})")
                    return best_b, best_sub
                else:
                    print(f"    Auditor: Semantically mapped '{bucket} -> {sub_bucket}' to '{possible_buckets[0]} -> {best_sub}' (Similarity: {best_sim:.3f})")
                    return possible_buckets[0], best_sub

    return "Unknown", "Unknown"

def export_completed_to_excel():
    """
    Queries SQLite database for all COMPLETED skills and writes them
    to the final output Excel file with the custom taxonomy columns.
    """
    conn = get_connection(PIPELINE_STATE_DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name, skill_bucket, skill_sub_bucket, summary, requires_review, review_reason
        FROM skills
        WHERE status = 'COMPLETED'
        ORDER BY skill_bucket, skill_sub_bucket, name
    """)
    rows = cursor.fetchall()
    conn.close()

    data = []
    for r in rows:
        data.append({
            "Skill Bucket": r["skill_bucket"],
            "Skill Sub-Bucket": r["skill_sub_bucket"],
            "Skill Name": r["name"],
            "One-liner Summary": r["summary"],
            "requires_review": r["requires_review"],
            "review_reason": r["review_reason"]
        })

    df = pd.DataFrame(data, columns=[
        "Skill Bucket", "Skill Sub-Bucket", "Skill Name", 
        "One-liner Summary", "requires_review", "review_reason"
    ])

    # Ensure output directory exists
    output_dir = os.path.dirname(config.OUTPUT_FILE)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    df.to_excel(config.OUTPUT_FILE, index=False)

def run_auditor():
    """
    Auditor Agent (Verification & Quality Control)
    Propagates classifications, runs taxonomy checks, flags uncertain items,
    marks records as COMPLETED, and updates the final Excel file.
    """
    print("Auditor Agent: Fetching all skills from state database...")
    skills = get_all_skills_for_audit()
    if not skills:
        print("Auditor Agent: No skills found in database to audit.")
        return False

    # Group skills by cluster_id
    clusters = {}
    for s in skills:
        cid = s["cluster_id"]
        if cid is not None:
            clusters.setdefault(cid, []).append(s)

    # Dictionary to store representative classifications (from CATEGORIZED or COMPLETED representatives)
    rep_classifications = {}
    for cid, members in clusters.items():
        rep = next((m for m in members if m["is_representative"] == 1), None)
        if not rep:
            rep = members[0]
        
        # If representative is categorized or already completed, cache its data
        if rep["skill_bucket"] is not None and rep["status"] in ["CATEGORIZED", "COMPLETED"]:
            rep_classifications[cid] = {
                "bucket": rep["skill_bucket"],
                "sub_bucket": rep["skill_sub_bucket"],
                "summary": rep["summary"]
            }

    audit_records = []
    propagated_count = 0
    updated_count = 0

    for s in skills:
        gid = s["global_id"]
        cid = s["cluster_id"]
        is_rep = s["is_representative"]
        status = s["status"]

        bucket = s["skill_bucket"]
        sub_bucket = s["skill_sub_bucket"]
        summary = s["summary"]
        requires_review = 0
        review_reason = []

        # We only audit skills that are ready:
        # A) Explicit SKIPPED_NOISE from ingestion
        # B) Representative skill is CATEGORIZED
        # C) Non-representative skill whose cluster rep is categorized
        ready_to_audit = False
        
        if status == "SKIPPED_NOISE":
            bucket = "Noise / Not a Skill"
            sub_bucket = "Noise / Not a Skill"
            summary = "Noise or typo filtered during ingestion."
            ready_to_audit = True
            
        elif status == "CATEGORIZED" and is_rep:
            ready_to_audit = True
            
        elif status in ["CLUSTERED", "WIKI_FETCHED"] and not is_rep and cid in rep_classifications:
            # Propagate from representative
            bucket = rep_classifications[cid]["bucket"]
            sub_bucket = rep_classifications[cid]["sub_bucket"]
            summary = rep_classifications[cid]["summary"]
            ready_to_audit = True
            propagated_count += 1
            
        elif status == "COMPLETED":
            # Already audited, retain as is
            continue

        if not ready_to_audit:
            # Not ready yet, skip auditing this skill
            continue

        # Run Audit Checks
        # 1. Fuzzy Check and Correct Taxonomy
        if bucket and bucket != "Unknown":
            corr_bucket, corr_sub = _fuzzy_correct_taxonomy(bucket, sub_bucket)
            if corr_bucket != bucket or corr_sub != sub_bucket:
                if corr_bucket == "Unknown" or corr_sub == "Unknown":
                    requires_review = 1
                    review_reason.append(f"Fuzzy match failed for LLM output '{bucket} -> {sub_bucket}'")
                else:
                    review_reason.append(f"Corrected '{bucket} -> {sub_bucket}' to '{corr_bucket} -> {corr_sub}'")
                bucket, sub_bucket = corr_bucket, corr_sub
        elif not bucket:
            bucket, sub_bucket, summary = "Unknown", "Unknown", ""

        # 2. Run Specific Review Flags
        if bucket == "Noise / Not a Skill":
            requires_review = 1
            review_reason.append("Categorized under Noise / Not a Skill")
        
        if bucket == "Unknown" or sub_bucket == "Unknown":
            requires_review = 1
            review_reason.append("Unknown taxonomy bucket or sub-bucket")

        users = s["users"]
        orig_status = s["original_status"]
        wiki_extract = s["wiki_extract"]
        if users == 0 and orig_status == 3 and (not wiki_extract or wiki_extract.strip() == ""):
            requires_review = 1
            review_reason.append("Users count is 0, status is 3, and lacks a Wikipedia entry")

        reason_str = "; ".join(review_reason) if review_reason else None

        audit_records.append((
            bucket,
            sub_bucket,
            summary,
            requires_review,
            reason_str,
            gid
        ))
        updated_count += 1

    # Save audited results back to database if any updates occurred
    if audit_records:
        save_audit_results(audit_records)
        print(f"Auditor Agent: Marked {updated_count} skills as COMPLETED (Propagated: {propagated_count}).")

    # Export all completed skills to Excel in real-time
    export_completed_to_excel()
    return True
