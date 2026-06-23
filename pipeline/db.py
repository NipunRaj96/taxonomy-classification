import sqlite3
import os
from pipeline.config import PIPELINE_STATE_DB, WIKI_CACHE_DB

def get_connection(db_path):
    """Returns a SQLite connection with dict factory enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(reset=False):
    """Initializes the SQLite state tracking and wiki cache databases."""
    # Initialize pipeline state tracking database
    if reset and os.path.exists(PIPELINE_STATE_DB):
        os.remove(PIPELINE_STATE_DB)
        
    conn_state = get_connection(PIPELINE_STATE_DB)
    cursor_state = conn_state.cursor()
    cursor_state.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            global_id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            users INTEGER,
            original_status INTEGER,
            top_1 TEXT,
            top_2 TEXT,
            top_3 TEXT,
            top_4 TEXT,
            top_5 TEXT,
            status TEXT DEFAULT 'PENDING',
            wiki_title TEXT,
            wiki_extract TEXT,
            cluster_id INTEGER,
            is_representative INTEGER DEFAULT 0,
            skill_bucket TEXT,
            skill_sub_bucket TEXT,
            summary TEXT,
            requires_review INTEGER DEFAULT 0,
            review_reason TEXT
        )
    """)
    conn_state.commit()
    conn_state.close()

    # Initialize Wikipedia cache database
    conn_cache = get_connection(WIKI_CACHE_DB)
    cursor_cache = conn_cache.cursor()
    cursor_cache.execute("""
        CREATE TABLE IF NOT EXISTS wiki_cache (
            query_title TEXT PRIMARY KEY,
            resolved_title TEXT,
            extract TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn_cache.commit()
    conn_cache.close()

def save_raw_skills(skills_records):
    """Saves raw skills records to the state database. Inserts or replaces."""
    conn = get_connection(PIPELINE_STATE_DB)
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT OR REPLACE INTO skills (
            global_id, name, users, original_status, 
            top_1, top_2, top_3, top_4, top_5, status
        ) VALUES (
            :global_id, :name, :users, :original_status,
            :top_1, :top_2, :top_3, :top_4, :top_5, :status
        )
    """, skills_records)
    conn.commit()
    conn.close()

def get_pending_wiki_skills():
    """Returns all skills with status 'PENDING' that need Wiki extracts."""
    conn = get_connection(PIPELINE_STATE_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT global_id, name FROM skills WHERE status = 'PENDING'")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def check_wiki_cache(query_titles):
    """Checks the wiki cache for a list of titles and returns matching dict."""
    if not query_titles:
        return {}
    conn = get_connection(WIKI_CACHE_DB)
    cursor = conn.cursor()
    # Chunk requests to prevent SQLite limits on parameters
    cache_results = {}
    chunk_size = 900
    for i in range(0, len(query_titles), chunk_size):
        chunk = query_titles[i:i+chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        cursor.execute(f"""
            SELECT query_title, resolved_title, extract 
            FROM wiki_cache 
            WHERE query_title IN ({placeholders})
        """, chunk)
        for row in cursor.fetchall():
            cache_results[row["query_title"]] = {
                "resolved_title": row["resolved_title"],
                "extract": row["extract"]
            }
    conn.close()
    return cache_results

def save_wiki_extracts(extracts_to_cache, skill_updates_state):
    """Saves extracts to wiki_cache.db and updates skill status in pipeline_state.db."""
    # Write to wiki_cache.db
    if extracts_to_cache:
        conn_cache = get_connection(WIKI_CACHE_DB)
        cursor_cache = conn_cache.cursor()
        cursor_cache.executemany("""
            INSERT OR REPLACE INTO wiki_cache (query_title, resolved_title, extract)
            VALUES (?, ?, ?)
        """, extracts_to_cache)
        conn_cache.commit()
        conn_cache.close()

    # Write to pipeline_state.db
    if skill_updates_state:
        conn_state = get_connection(PIPELINE_STATE_DB)
        cursor_state = conn_state.cursor()
        cursor_state.executemany("""
            UPDATE skills 
            SET wiki_title = ?, wiki_extract = ?, status = 'WIKI_FETCHED'
            WHERE name = ?
        """, skill_updates_state)
        conn_state.commit()
        conn_state.close()

def get_valid_skills_for_clustering():
    """Returns skills with status 'WIKI_FETCHED' to be clustered."""
    conn = get_connection(PIPELINE_STATE_DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT global_id, name, users, wiki_extract 
        FROM skills 
        WHERE status = 'WIKI_FETCHED'
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_cluster_assignments(assignments):
    """Saves cluster ID and representative flag for skills in bulk."""
    conn = get_connection(PIPELINE_STATE_DB)
    cursor = conn.cursor()
    cursor.executemany("""
        UPDATE skills 
        SET cluster_id = ?, is_representative = ?, status = 'CLUSTERED'
        WHERE global_id = ?
    """, assignments)
    conn.commit()
    conn.close()

def get_pending_representative_skills():
    """Returns representative skills that need LLM categorization."""
    conn = get_connection(PIPELINE_STATE_DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT global_id, name, wiki_extract, top_1, top_2, top_3, top_4, top_5 
        FROM skills 
        WHERE status = 'CLUSTERED' AND is_representative = 1
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_llm_result(global_id, bucket, sub_bucket, summary):
    """Saves LLM categorization output back to a representative skill."""
    conn = get_connection(PIPELINE_STATE_DB)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE skills 
        SET skill_bucket = ?, skill_sub_bucket = ?, summary = ?, status = 'CATEGORIZED'
        WHERE global_id = ?
    """, (bucket, sub_bucket, summary, global_id))
    conn.commit()
    conn.close()

def get_all_skills_for_audit():
    """Returns all rows in the skills table to compile the final audited output."""
    conn = get_connection(PIPELINE_STATE_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM skills")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_audit_results(audit_records):
    """Updates the final columns for all skills (propagation & fuzzy correction)."""
    conn = get_connection(PIPELINE_STATE_DB)
    cursor = conn.cursor()
    cursor.executemany("""
        UPDATE skills 
        SET skill_bucket = ?, skill_sub_bucket = ?, summary = ?, 
            requires_review = ?, review_reason = ?, status = 'COMPLETED'
        WHERE global_id = ?
    """, audit_records)
    conn.commit()
    conn.close()
