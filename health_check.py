import os
import sqlite3
import sys
from pathlib import Path
from dotenv import load_dotenv

# ANSI Colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

def check_env() -> bool:
    load_dotenv()
    env_path = Path(".env")
    if not env_path.exists():
        print(f"  {RED}[ FAIL ]{RESET} Environment Configuration - .env file not found. Copy .env.example to .env")
        return False

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print(f"  {YELLOW}[ WARN ]{RESET} Gemini API Configuration - GOOGLE_API_KEY not found. Fallback to rule-based parsing.")
    elif api_key.strip() == "" or "your" in api_key.lower():
        print(f"  {YELLOW}[ WARN ]{RESET} Gemini API Configuration - GOOGLE_API_KEY has placeholder values. Fallback to rule-based parsing.")
    else:
        print(f"  {GREEN}[ OK ]{RESET} Gemini API Configuration - GOOGLE_API_KEY detected.")
    return True

def check_directories() -> bool:
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # Check writability
    test_file = logs_dir / ".write_test"
    try:
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()
        print(f"  {GREEN}[ OK ]{RESET} Logs Directory Writability - logs/ is writable.")
        return True
    except Exception as e:
        print(f"  {RED}[ FAIL ]{RESET} Logs Directory Writability - Cannot write to logs/: {e}")
        return False

def check_database() -> bool:
    db_path = Path("logs/events.db")
    if not db_path.exists():
        print(f"  {YELLOW}[ WARN ]{RESET} SQLite Buffer Database - logs/events.db does not exist yet (created on ingestion).")
        return True

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        print(f"  {GREEN}[ OK ]{RESET} SQLite Buffer Database - Connected. Tables found: {', '.join(tables)}")
        return True
    except Exception as e:
        print(f"  {RED}[ FAIL ]{RESET} SQLite Buffer Database - Database connection failed: {e}")
        return False

def check_chromadb() -> bool:
    chroma_dir = Path("vectorstore/chroma")
    fallback_store = chroma_dir / "fallback_store.json"
    
    # 1. Check fallback json
    if not fallback_store.exists():
        print(f"  {YELLOW}[ WARN ]{RESET} Vector Store Fallback (JSON) - fallback_store.json not found. Run ingestion/embedder.py.")
    else:
        try:
            with open(fallback_store, encoding='utf-8') as f:
                import json
                data = json.load(f)
                print(f"  {GREEN}[ OK ]{RESET} Vector Store Fallback (JSON) - Found. Loaded {len(data)} runbooks.")
        except Exception as e:
            print(f"  {RED}[ FAIL ]{RESET} Vector Store Fallback (JSON) - Failed to read fallback store: {e}")

    # 2. Check Chroma Persistent DB
    if not chroma_dir.exists():
        print(f"  {YELLOW}[ WARN ]{RESET} Chroma Vector Store - vectorstore/chroma/ does not exist. Fallback mode will be used.")
        return True

    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(chroma_dir.resolve()))
        collections = client.list_collections()
        has_runbooks = any(c.name == "runbooks" for c in collections)
        
        if has_runbooks:
            collection = client.get_collection(name="runbooks")
            count = collection.count()
            if count > 0:
                print(f"  {GREEN}[ OK ]{RESET} Chroma Vector Store - Collection 'runbooks' has {count} documents.")
            else:
                print(f"  {YELLOW}[ WARN ]{RESET} Chroma Vector Store - Collection 'runbooks' is empty. Seed via ingestion/embedder.py.")
        else:
            print(f"  {YELLOW}[ WARN ]{RESET} Chroma Vector Store - Collection 'runbooks' not found. Run ingestion/embedder.py.")
    except ImportError:
        print(f"  {YELLOW}[ WARN ]{RESET} Chroma Vector Store - chromadb not loaded. Falling back to local search.")
    except Exception as e:
        print(f"  {RED}[ FAIL ]{RESET} Chroma Vector Store - Failed to initialize client: {e}")
    
    return True

def run_diagnostics() -> bool:
    print(f"\n{BOLD}=================================================={RESET}")
    print(f"{BOLD}SENTRY-SWARM PRE-FLIGHT SYSTEM DIAGNOSTICS{RESET}")
    print(f"{BOLD}=================================================={RESET}")

    success = True
    success = check_env() and success
    success = check_directories() and success
    success = check_database() and success
    success = check_chromadb() and success

    print(f"{BOLD}=================================================={RESET}")
    if success:
        print(f"{GREEN}{BOLD}Pre-flight diagnostics completed successfully.{RESET}")
    else:
        print(f"{RED}{BOLD}Pre-flight diagnostics finished with errors. Inspect warnings above.{RESET}")
    print(f"{BOLD}==================================================\n{RESET}")
    return success

if __name__ == "__main__":
    run_diagnostics()
