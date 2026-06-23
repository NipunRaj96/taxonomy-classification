import argparse
import sys
import time
import os
from pipeline.noise_filter import run_cleaner
from pipeline.wiki_harvester import run_wiki_harvester
from pipeline.clusterer import run_clusterer
from pipeline.llm_worker import run_llm_worker
from pipeline.auditor import run_auditor
import pipeline.config as config

def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Skill Categorization & Summarization Pipeline")
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Reset the pipeline database and start ingestion from scratch."
    )
    parser.add_argument(
        "--run-agent",
        choices=["cleaner", "librarian", "architect", "expert", "auditor"],
        help="Run only a single specific agent."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of records processed by Librarian (Wikipedia) or Expert (LLM) agents."
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Ingest and run on a random sample of N records from the master dataset."
    )
    parser.add_argument(
        "--model",
        choices=["3b", "7b"],
        default="3b",
        help="Select the model size to use: 3b (Qwen2.5-3B) or 7b (Qwen2.5-7B)."
    )

    args = parser.parse_args()

    # Dynamic model configuration
    config.set_model(args.model)

    # Delete previous output file at the start of execution (model-specific)
    if os.path.exists(config.OUTPUT_FILE):
        print(f"Orchestrator: Deleting previous output file at {config.OUTPUT_FILE}...")
        try:
            os.remove(config.OUTPUT_FILE)
        except Exception as e:
            print(f"Orchestrator Warning: Could not delete output file: {e}")

    t_start = time.time()
    db_exists = os.path.exists(config.PIPELINE_STATE_DB)

    # 1. Cleaner Agent
    if args.run_agent == "cleaner" or (not args.run_agent and (args.reset_state or not db_exists)):
        print("\n=== [Stage 1] Cleaner Agent ===")
        run_cleaner(reset=args.reset_state or args.sample_size is not None, sample_size=args.sample_size)
        if args.run_agent == "cleaner":
            sys.exit(0)

    # 2. Librarian Agent
    if args.run_agent == "librarian" or not args.run_agent:
        print("\n=== [Stage 2] Librarian Agent (Context Harvester) ===")
        run_wiki_harvester(limit=args.limit)
        if args.run_agent == "librarian":
            sys.exit(0)

    # 3. Architect Agent
    if args.run_agent == "architect" or not args.run_agent:
        print("\n=== [Stage 3] Architect Agent (Semantic Clusterer) ===")
        run_clusterer()
        if args.run_agent == "architect":
            sys.exit(0)

    # 4. Expert Agent
    if args.run_agent == "expert" or not args.run_agent:
        print("\n=== [Stage 4] Expert Agent (LLM Categorizer) ===")
        run_llm_worker(limit=args.limit)
        if args.run_agent == "expert":
            sys.exit(0)

    # 5. Auditor Agent
    if args.run_agent == "auditor" or not args.run_agent:
        print("\n=== [Stage 5] Auditor Agent (Verification & Excel Export) ===")
        run_auditor()
        if args.run_agent == "auditor":
            sys.exit(0)

    print(f"\nPipeline execution finished in {time.time() - t_start:.2f} seconds.")

if __name__ == "__main__":
    main()
