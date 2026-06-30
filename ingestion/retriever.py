import json
import logging
from pathlib import Path

logger = logging.getLogger("retriever")

VECTORSTORE_DIR = Path("vectorstore/chroma")
FALLBACK_FILE = VECTORSTORE_DIR / "fallback_store.json"

def retrieve_relevant_runbook(query_text: str, incident_type: str | None = None) -> dict | None:
    """
    Retrieves the most relevant runbook content for the incident.
    First tries to retrieve via Chroma vector store, falling back to local file parsing
    if Chroma is unavailable or has not been seeded.
    
    Returns a dict containing:
        - name: runbook filename
        - path: absolute path to the runbook
        - incident_type: type of incident (e.g. oom_kill)
        - content: markdown text contents of the runbook
    """
    logger.info("Attempting runbook retrieval (type: %s, query: %s)", incident_type, query_text[:40])
    
    # 1. Try ChromaDB if available
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(VECTORSTORE_DIR.resolve()))
        # Check if collection exists
        collections = client.list_collections()
        has_collection = any(c.name == "runbooks" for c in collections)
        
        if has_collection:
            collection = client.get_collection(name="runbooks")
            if collection.count() > 0:
                # If we have an exact incident_type filter, we can apply it
                where_clause = {}
                if incident_type:
                    where_clause = {"incident_type": incident_type}
                    
                results = collection.query(
                    query_texts=[query_text],
                    n_results=1,
                    where=where_clause if where_clause else None
                )
                
                if results and results["documents"] and results["documents"][0]:
                    doc = results["documents"][0][0]
                    meta = results["metadatas"][0][0]
                    logger.info("Retrieved runbook '%s' via ChromaDB query", meta["name"])
                    return {
                        "name": meta["name"],
                        "path": meta["path"],
                        "incident_type": meta["incident_type"],
                        "content": doc
                    }
    except Exception as e:
        logger.warning("ChromaDB retrieval failed or not configured, falling back: %s", e)

    # 2. Fallback: Parse local fallback store JSON or read files directly
    logger.info("Falling back to local file search...")
    if FALLBACK_FILE.exists():
        try:
            with open(FALLBACK_FILE, "r", encoding="utf-8") as f:
                runbooks = json.load(f)
                
            # If incident_type matches exactly, return it
            if incident_type:
                for rb in runbooks:
                    if rb["incident_type"] == incident_type:
                        logger.info("Retrieved runbook '%s' via exact type match in fallback store", rb["name"])
                        return rb
                        
            # Otherwise, do simple keyword matching score
            best_rb = None
            best_score = -1
            query_words = set(query_text.lower().split())
            
            for rb in runbooks:
                score = sum(1 for word in query_words if word in rb["content"].lower())
                # boost if the filename is in the query
                if rb["incident_type"].lower() in query_text.lower():
                    score += 10
                if score > best_score:
                    best_score = score
                    best_rb = rb
                    
            if best_rb and best_score > 0:
                logger.info("Retrieved runbook '%s' via keyword search in fallback store (score=%d)", best_rb["name"], best_score)
                return best_rb
        except Exception as e:
            logger.error("Failed to read fallback store: %s", e)

    # 3. Last resort fallback: read directly from runbooks folder
    runbooks_dir = Path("runbooks")
    if runbooks_dir.exists():
        for p in runbooks_dir.glob("*.md"):
            if p.name == "README.md":
                continue
            # Simple check if the file name contains the incident type
            if incident_type and incident_type in p.name:
                logger.info("Retrieved runbook '%s' via runbooks directory scanning", p.name)
                try:
                    return {
                        "name": p.name,
                        "path": str(p.resolve()),
                        "incident_type": incident_type,
                        "content": p.read_text(encoding="utf-8")
                    }
                except Exception:
                    pass

    logger.warning("No matching runbook retrieved")
    return None
