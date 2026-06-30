import os
import json
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("embedder")

RUNBOOKS_DIR = Path("runbooks")
VECTORSTORE_DIR = Path("vectorstore/chroma")
FALLBACK_FILE = VECTORSTORE_DIR / "fallback_store.json"

def parse_runbook(path: Path) -> dict:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    # Try to find incident type
    incident_type = None
    for i, line in enumerate(lines):
        if line.strip() == "## Incident Type" and i + 1 < len(lines):
            # check the next few lines for a non-empty line
            for j in range(i + 1, len(lines)):
                val = lines[j].strip()
                if val:
                    incident_type = val
                    break
            break
            
    if not incident_type:
        # Fallback to file basename matching
        name = path.stem
        if "5xx" in name:
            incident_type = "http_5xx"
        elif "timeout" in name:
            incident_type = "db_timeout"
        elif "oom" in name:
            incident_type = "oom_kill"
        elif "deploy" in name:
            incident_type = "failed_deploy"
        elif "cascading" in name:
            incident_type = "cascading_failure"
        else:
            incident_type = name

    return {
        "name": path.name,
        "path": str(path.resolve()),
        "incident_type": incident_type,
        "content": content
    }

def main():
    logger.info("Starting runbook ingestion...")
    VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)
    
    runbooks = []
    for p in RUNBOOKS_DIR.glob("*.md"):
        if p.name == "README.md":
            continue
        try:
            rb_data = parse_runbook(p)
            runbooks.append(rb_data)
            logger.info("Parsed runbook: %s (incident_type: %s)", p.name, rb_data["incident_type"])
        except Exception as e:
            logger.error("Failed to parse runbook %s: %s", p.name, e)
            
    # Always save fallback json
    try:
        with open(FALLBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(runbooks, f, indent=2)
        logger.info("Saved fallback store to %s", FALLBACK_FILE)
    except Exception as e:
        logger.error("Failed to save fallback store: %s", e)

    # Try importing chromadb to write to real chroma vector store
    try:
        import chromadb
        logger.info("ChromaDB library available. Initializing PersistentClient...")
        
        # Initialize chroma client
        client = chromadb.PersistentClient(path=str(VECTORSTORE_DIR.resolve()))
        
        # Get or create collection
        collection = client.get_or_create_collection(name="runbooks")
        
        # Upsert documents
        ids = []
        documents = []
        metadatas = []
        
        for idx, rb in enumerate(runbooks):
            ids.append(f"runbook-{idx}")
            documents.append(rb["content"])
            metadatas.append({
                "name": rb["name"],
                "incident_type": rb["incident_type"],
                "path": rb["path"]
            })
            
        if ids:
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            logger.info("Successfully loaded %d documents into Chroma collection 'runbooks'", len(ids))
        else:
            logger.warning("No documents found to load into Chroma")
            
    except ImportError:
        logger.info("ChromaDB library not available or failed to load. Operating in Fallback/JSON-only mode.")
    except Exception as e:
        logger.error("Failed to write to ChromaDB: %s", e)

if __name__ == "__main__":
    main()
