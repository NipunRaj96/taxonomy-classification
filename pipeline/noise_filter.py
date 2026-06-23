import pandas as pd
import re
import os
from pipeline.config import INPUT_FILE
from pipeline.db import save_raw_skills, init_db

def run_cleaner(reset=False, sample_size=None):
    """
    Cleaner Agent (Ingestion & Pre-filtering)
    Reads raw skills Excel, applies deterministic noise rules,
    and inserts records into the SQLite database.
    """
    print("Cleaner Agent: Starting Ingestion...")
    if not os.path.exists(INPUT_FILE):
        raise FileNotFoundError(f"Input file not found at {INPUT_FILE}")

    # Initialize the database
    init_db(reset=reset)

    print(f"Cleaner Agent: Reading {INPUT_FILE}...")
    df = pd.read_excel(INPUT_FILE)
    if sample_size is not None:
        print(f"Cleaner Agent: Randomly sampling {sample_size} records...")
        df = df.sample(n=sample_size, random_state=42)
    print(f"Cleaner Agent: Ingesting {len(df)} records...")

    skills_records = []
    noise_count = 0

    for _, row in df.iterrows():
        # Trim name and convert missing to empty string
        raw_name = str(row["name"]).strip() if pd.notna(row["name"]) else ""
        global_id = int(row["global_id"])
        users = int(row["users"]) if pd.notna(row["users"]) else 0
        original_status = int(row["status"]) if pd.notna(row["status"]) else 0

        # Mappings for related terms
        top_1 = str(row["top_1"]).strip() if pd.notna(row["top_1"]) else None
        top_2 = str(row["top_2"]).strip() if pd.notna(row["top_2"]) else None
        top_3 = str(row["top_3"]).strip() if pd.notna(row["top_3"]) else None
        top_4 = str(row["top_4"]).strip() if pd.notna(row["top_4"]) else None
        top_5 = str(row["top_5"]).strip() if pd.notna(row["top_5"]) else None

        # Noise checks
        is_noise = False
        if not raw_name:
            is_noise = True
        elif len(raw_name) == 1 and raw_name.upper() not in ["C", "R"]:
            is_noise = True
        elif raw_name.isdigit():  # Pure digit string
            is_noise = True
        elif re.match(r"^[^a-zA-Z0-9]+$", raw_name):  # Punctuation only
            is_noise = True

        status = "SKIPPED_NOISE" if is_noise else "PENDING"
        if is_noise:
            noise_count += 1

        skills_records.append({
            "global_id": global_id,
            "name": raw_name,
            "users": users,
            "original_status": original_status,
            "top_1": top_1,
            "top_2": top_2,
            "top_3": top_3,
            "top_4": top_4,
            "top_5": top_5,
            "status": status
        })

    # Bulk insert
    save_raw_skills(skills_records)
    print(f"Cleaner Agent Finished: Ingested {len(skills_records)} skills. "
          f"Flagged {noise_count} obvious noise skills as SKIPPED_NOISE.")
    return len(skills_records), noise_count
