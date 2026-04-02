import os
import sys
import locale
import uuid
import shutil
import secrets
from datetime import datetime
from typing import List, Optional, Tuple
import json

if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

try:
    locale.setlocale(locale.LC_ALL, 'el_GR.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'C.UTF-8')
    except locale.Error:
        pass

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, FileResponse

from .cf_ai import embed_texts, chat, build_rag_prompt, count_tokens_llama, validate_token_budget, calculate_optimal_k
import requests
from .index_store import Chunk, FaissStore
from .pdf_utils import extract_pdf_text_with_pages, chunk_text
from .pptx_utils import extract_pptx_text_with_slides
from .file_utils import safe_filename
from .chat_history import ChatHistoryStore

MAX_BYTES = 50 * 1024 * 1024

class FileIngestError(Exception):
    def __init__(self, reason: str, stage: str): 
        super().__init__(reason)
        self.reason = reason
        self.stage = stage

DATA_DIR = os.getenv("DATA_DIR", "./data")
INDEX_DIR = os.path.join(DATA_DIR, "index")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
LOG_DIR = os.path.join(DATA_DIR, "logs")
CHAT_HISTORY_DIR = os.path.join(DATA_DIR, "chat_history")
SESSION_OWNERS_DIR = os.path.join(DATA_DIR, "session_owners")
LOG_PATH = os.path.join(LOG_DIR, "flow_log.txt")

def get_session_index_paths(session_id: str, create_if_missing: bool = False) -> Tuple[str, str]:
    session_dir = os.path.join(INDEX_DIR, f"session_{session_id}")
    if create_if_missing:
        os.makedirs(session_dir, exist_ok=True)
    index_path = os.path.join(session_dir, "index.faiss")
    meta_path = os.path.join(session_dir, "metadata.json")
    return index_path, meta_path

def get_session_upload_dir(session_id: str, create_if_missing: bool = False) -> str:
    session_dir = os.path.join(UPLOADS_DIR, f"session_{session_id}")
    if create_if_missing:
        os.makedirs(session_dir, exist_ok=True)
    return session_dir

def get_session_owner_path(session_id: str) -> str:
    return os.path.join(SESSION_OWNERS_DIR, f"{session_id}.json")

def _normalize_session_id(session_id: str) -> str:
    value = (session_id or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Session ID is required.")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if any(ch not in allowed for ch in value):
        raise HTTPException(status_code=400, detail="Invalid session ID.")
    return value

def _require_session_key(x_session_key: Optional[str]) -> str:
    value = (x_session_key or "").strip()
    if not value:
        raise HTTPException(status_code=401, detail="Missing session key.")
    return value

def _load_session_owner(session_id: str) -> Optional[dict]:
    path = get_session_owner_path(session_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _claim_or_verify_session(session_id: str, session_key: str) -> None:
    session_id = _normalize_session_id(session_id)
    session_key = _require_session_key(session_key)
    owner = _load_session_owner(session_id)
    if owner:
        if owner.get("owner_key") != session_key:
            raise HTTPException(status_code=403, detail="Access to this session is not allowed.")
        return

    os.makedirs(SESSION_OWNERS_DIR, exist_ok=True)
    owner_data = {
        "session_id": session_id,
        "owner_key": session_key,
        "created_at": datetime.now().isoformat(),
        "nonce": secrets.token_hex(8)
    }
    with open(get_session_owner_path(session_id), "w", encoding="utf-8") as f:
        json.dump(owner_data, f, ensure_ascii=False, indent=2)

def _delete_session_owner(session_id: str) -> None:
    try:
        owner_path = get_session_owner_path(session_id)
        if os.path.exists(owner_path):
            os.remove(owner_path)
    except Exception:
        pass

app = FastAPI(title="ChatDocuments")

allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
if allowed_origins_env:
    allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]
else:
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allowed_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

def _ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(INDEX_DIR, exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(CHAT_HISTORY_DIR, exist_ok=True)
    os.makedirs(SESSION_OWNERS_DIR, exist_ok=True)

class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        try:
            path = request.url.path
        except Exception:
            path = ""
        if path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheStaticMiddleware)

def _log_reset() -> None:
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"[#] New session: {datetime.now().isoformat(timespec='seconds')}\n")
    except Exception:
        pass

def _log_add(line: str) -> None:
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
    except Exception:
        pass

async def _process_one_file(up: UploadFile, session_id: str) -> Tuple[List[Chunk], List[str], str, dict]:
    original_filename = up.filename or f'file_{uuid.uuid4().hex}'
    original_ext = os.path.splitext(original_filename)[1].lower()
    base_name = safe_filename(original_filename)
    
    if not base_name.endswith(original_ext) and original_ext:
        original_name = base_name + original_ext
    else:
        original_name = base_name
    
    session_upload_dir = get_session_upload_dir(session_id, create_if_missing=True)
    saved_file_path = os.path.join(session_upload_dir, original_name)
    tmp_path = os.path.join(session_upload_dir, f"upload_{uuid.uuid4().hex}_{original_name}")

    bytes_written = 0
    try:
        with open(tmp_path, "wb") as fout:
            while True:
                chunk = await up.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > MAX_BYTES:
                    raise FileIngestError("File is too large", "upload")
                fout.write(chunk)
        await up.close()
        
        if bytes_written == 0:
            raise FileIngestError("Empty file", "upload")

        ext = original_ext if original_ext else os.path.splitext(original_name)[1].lower()
        if ext == ".pdf":
            pairs = extract_pdf_text_with_pages(tmp_path)
        elif ext == ".pptx":
            pairs = extract_pptx_text_with_slides(tmp_path)
        else:
            ext_display = ext if ext else "(no extension)"
            _log_add(f"Error: Unsupported file type '{ext_display}' for '{original_filename}'")
            raise FileIngestError(
                f"Unsupported file type: '{ext_display}'. "
                f"Supported types: .pdf, .pptx. Original filename: '{original_filename}'",
                "validate"
            )

        full_text = "\n\n".join([text for _, text in pairs if text.strip()])
        total_tokens = count_tokens_llama(full_text)
        MAX_TOKENS_PER_FILE = 50000
        
        if total_tokens > MAX_TOKENS_PER_FILE:
            raise FileIngestError(
                f"The document is too large (~{total_tokens:,} tokens). "
                f"Maximum allowed: {MAX_TOKENS_PER_FILE:,} tokens. "
                f"Please split the document into smaller parts.",
                "token_limit"
            )

        # Δημιουργία τμημάτων κειμένου για τη διαδικασία αναζήτησης
        chunks, texts = [], []
        for page_num, text in pairs:
            for ch in chunk_text(text, prefix=f"{os.path.splitext(original_name)[0]}"):
                chunk_tokens = count_tokens_llama(ch)
                chunks.append(Chunk(source=original_name, page=page_num, text=ch, session_id=session_id, tokens=chunk_tokens))
                texts.append(ch)
                
        if not texts:
            raise FileIngestError("Δεν εξήχθη κείμενο", "parse")
        
        # Μετακίνηση του αρχείου στην τελική διαδρομή αποθήκευσης
        if not os.path.exists(saved_file_path):
            shutil.move(tmp_path, saved_file_path)
        else:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        
        # Συλλογή πληροφοριών και στατιστικών του εγγράφου
        metadata = {
            "filename": original_name,
            "tokens": total_tokens,
            "pages": len([p for p, t in pairs if t.strip()]),
            "chunks": len(texts),
            "characters": len(full_text),
            "words": len(full_text.split()),
            "session_id": session_id,
            "uploaded_at": datetime.now().isoformat()
        }
        
        # Αποθήκευση των πληροφοριών σε αρχείο JSON
        json_path = os.path.join(session_upload_dir, f"{os.path.splitext(original_name)[0]}.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _log_add(f"Προειδοποίηση: Αποτυχία αποθήκευσης JSON για {original_name}: {e}")
        
        return chunks, texts, original_name, metadata
        
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise

_ensure_dirs()
chat_history_store = ChatHistoryStore(CHAT_HISTORY_DIR)

# Μαζική εισαγωγή αρχείων και ενημέρωση του ευρετηρίου
@app.post("/index/batch")
async def index_files(
    files: Optional[List[UploadFile]] = File(default=None, description="Λίστα αρχείων προς μεταφόρτωση (.pdf, .pptx)"),
    file: Optional[UploadFile] = File(default=None, description="Ένα μεμονωμένο αρχείο προς μεταφόρτωση"),
    session_id: str = Form(default=None, description="Το ID της τρέχουσας συνεδρίας"),
    strict: bool = Form(default=False, description="Αυστηρή λειτουργία (διακοπή σε σφάλμα)"),
    manifest: Optional[str] = Form(default=None, description="Λίστα αναμενόμενων αρχείων σε μορφή JSON"),
    x_session_key: Optional[str] = Header(default=None)
):
    _ensure_dirs()
    
    inputs: List[UploadFile] = []
    if files:
        inputs.extend(files)
    if file:
        inputs.append(file)
    if not inputs:
        return JSONResponse({"ok": False, "error": "No files were selected.", "session_id": session_id}, status_code=400)

    if not session_id:
        session_id = str(uuid.uuid4())
    session_id = _normalize_session_id(session_id)
    _claim_or_verify_session(session_id, x_session_key)

    expected = set()
    if manifest:
        try:
            expected = set(json.loads(manifest))
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid manifest.", "session_id": session_id}, status_code=400)

    # Υπολογισμός υπαρχόντων δεδομένων στη συνεδρία
    index_path, meta_path = get_session_index_paths(session_id, create_if_missing=False)
    existing_session_tokens = 0
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                existing_metadata = json.load(f)
                for chunk_data in existing_metadata:
                    cached_tokens = chunk_data.get("tokens", 0)
                    if cached_tokens > 0:
                        existing_session_tokens += cached_tokens
                    else:
                        chunk_text = chunk_data.get("text", "")
                        existing_session_tokens += count_tokens_llama(chunk_text)
        except Exception:
            pass

    processed, failures = [], []
    all_chunks, all_texts = [], []
    new_documents_tokens = 0

    # Επεξεργασία κάθε αρχείου ξεχωριστά
    for up in inputs:
        try:
            chunks, texts, name, doc_metadata = await _process_one_file(up, session_id)
            doc_tokens = doc_metadata.get("tokens", 0)
            
            # Επικύρωση ορίων χρήσης για τη συνεδρία
            is_valid, error_msg, validation_details = validate_token_budget(
                new_document_tokens=doc_tokens,
                existing_session_tokens=existing_session_tokens + new_documents_tokens
            )
            
            if not is_valid:
                failures.append({
                    "name": name, 
                    "reason": error_msg, 
                    "stage": "token_validation",
                    "details": validation_details
                })
                continue
            
            all_chunks.extend(chunks)
            all_texts.extend(texts)
            new_documents_tokens += doc_tokens
            processed.append({
                "name": name, 
                "chunks": len(texts),
                "tokens": doc_tokens,
                "pages": doc_metadata.get("pages", 0)
            })
        except FileIngestError as e:
            failures.append({"name": up.filename or "Unknown", "reason": e.reason, "stage": e.stage})
        except Exception as e:
            failures.append({"name": up.filename or "Unknown", "reason": f"Unexpected error: {str(e)}", "stage": "unknown"})

    received_names = {p["name"] for p in processed} | {f["name"] for f in failures}
    missing = [n for n in expected if n not in received_names]
    failures.extend({"name": n, "reason": "File was not received", "stage": "upload"} for n in missing)

    if strict and failures:
        return JSONResponse({"ok": False, "mode": "strict", "processed": processed, "failed": failures, "session_id": session_id}, status_code=409)

    if not all_texts:
        if failures:
            error_msg = "No valid documents were processed. "
            if len(failures) == 1:
                error_msg += f"File '{failures[0]['name']}' failed: {failures[0].get('reason', 'Unknown error')}"
            else:
                error_msg += f"{len(failures)} files failed. Check the details for more information."
        else:
            error_msg = "No valid documents were processed."
        
        try:
            session_dir = os.path.dirname(index_path)
            if os.path.exists(session_dir) and not os.listdir(session_dir):
                os.rmdir(session_dir)
                _log_add(f"Cleaned empty session directory: {session_dir}")
        except Exception as cleanup_error:
            _log_add(f"Warning: Failed to clean session directory: {cleanup_error}")
        
        return JSONResponse({"ok": False, "error": error_msg, "failed": failures, "session_id": session_id}, status_code=400)

    try:
        index_path, meta_path = get_session_index_paths(session_id, create_if_missing=True)
        store = FaissStore(dim=1024, index_path=index_path, meta_path=meta_path)
        store.load()
        
        incoming_names = {p["name"] for p in processed}
        has_prev_any = any(c.source in incoming_names for c in getattr(store, "metadata", []))

        # Δημιουργία ή ενημέρωση της διανυσματικής αποθήκης
        if not has_prev_any and len(getattr(store, "metadata", [])) == 0:
            vectors = embed_texts(all_texts)
            dim = vectors.shape[1]
            if getattr(store, "dim", dim) != dim:
                store = FaissStore(dim=dim, index_path=index_path, meta_path=meta_path)
            store.add(vectors, all_chunks)
            store.save()
            status = 207 if failures else 200
            return JSONResponse({
                "ok": True, "processed": processed, "failed": failures,
                "chunks_added": len(all_texts), "replaced": False, "session_id": session_id
            }, status_code=status)

        remaining = [c for c in getattr(store, "metadata", [])
                     if c.source not in incoming_names]
        merged_chunks = remaining + all_chunks
        merged_texts = [c.text for c in merged_chunks]
        vectors_all = embed_texts(merged_texts)
        new_store = FaissStore(dim=vectors_all.shape[1], index_path=index_path, meta_path=meta_path)
        new_store.add(vectors_all, merged_chunks)
        new_store.save()

        status = 207 if failures else 200
        return JSONResponse({
            "ok": True, "processed": processed, "failed": failures,
            "chunks_added": len(all_texts), "total_chunks": len(merged_texts),
            "replaced": has_prev_any, "session_id": session_id
        }, status_code=status)

    except requests.exceptions.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", 502) or 502
        if status == 429:
            msg = "Rate limit exceeded (429). Please try again shortly."
        elif status in (401, 403):
            msg = "Insufficient permissions (401/403)."
        else:
            msg = f"Upstream error ({status})."
        _log_add(f"HTTP error: {msg}")
        return JSONResponse({"ok": False, "error": msg, "processed": processed, "failed": failures, "session_id": session_id}, status_code=status)
    except Exception as e:
        import traceback
        error_msg = str(e)
        tb = traceback.format_exc()
        _log_add(f"Server error: {error_msg}")
        _log_add(f"Traceback: {tb}")
        print(f"ERROR in index_files: {error_msg}", file=sys.stderr)
        print(tb, file=sys.stderr)
        
        try:
            session_dir = os.path.dirname(index_path)
            if os.path.exists(session_dir) and not os.path.exists(index_path) and not os.path.exists(meta_path):
                if not os.listdir(session_dir):
                    os.rmdir(session_dir)
                    _log_add(f"Cleaned empty session directory after error: {session_dir}")
        except Exception as cleanup_error:
            _log_add(f"Warning: Failed to clean session directory: {cleanup_error}")
        
        return JSONResponse({"ok": False, "error": f"Server error: {error_msg}", "processed": processed, "failed": failures, "session_id": session_id}, status_code=500)

# Υποβολή ερωτήματος και λήψη απάντησης από το μοντέλο AI
@app.post("/query")
async def query_pdf(
    question: str = Form(..., description="User question about the uploaded documents"),
    k: int = Form(5, description="Number of chunks to retrieve"),
    use_llm: str = Form("1", description="Use the LLM for answering (1=yes, 0=no)"),
    llm_extractive: str = Form("0", description="Extractive answer mode"),
    session_id: str = Form(default=None, description="Current session ID"),
    x_session_key: Optional[str] = Header(default=None)
):
    _ensure_dirs()

    if not session_id:
        return JSONResponse({
            "ok": False,
            "error": "No active session found. Start a new chat to continue."
        }, status_code=400)

    session_id = _normalize_session_id(session_id)
    _claim_or_verify_session(session_id, x_session_key)

    if not (question or "").strip():
        return JSONResponse({"ok": False, "error": "The question cannot be empty."}, status_code=400)

    index_path, meta_path = get_session_index_paths(session_id, create_if_missing=False)
    store = FaissStore(dim=1024, index_path=index_path, meta_path=meta_path)
    try:
        store.load()

        if not store.metadata:
            return JSONResponse({
                "ok": False,
                "error": "No documents uploaded yet. Upload a PDF or PowerPoint file first."
            }, status_code=400)

        total_chunks = len(store.metadata)
        total_tokens = sum(chunk.tokens if chunk.tokens > 0 else count_tokens_llama(chunk.text) for chunk in store.metadata)
        unique_pages = set((chunk.source, chunk.page) for chunk in store.metadata)
        total_pages = len(unique_pages)
        
        if k <= 10:
            suggested_k = calculate_optimal_k(
                total_chunks=total_chunks,
                total_tokens=total_tokens
            )
            k = max(suggested_k, 8)
            _log_add(f"Dynamic k selection: using k={k} (total_chunks={total_chunks}, pages={total_pages})")

        # Μετατροπή ερώτησης σε διάνυσμα και αναζήτηση σχετικών τμημάτων
        q_vec = embed_texts([question])[0]
        _log_add(f"Question: '{question}' | k={k} | use_llm={use_llm} | extractive={llm_extractive} | session_id={session_id}")

        results = store.search(q_vec, k=k)
        try:
            for rank, (score, c) in enumerate(results, start=1):
                _log_add(f"Top{rank}: source='{c.source}', page={c.page}, score={score:.4f}")
        except Exception:
            pass

        if not results:
            return JSONResponse({
                "ok": False,
                "error": "No relevant excerpts were found for this question.",
                "session_id": session_id
            }, status_code=400)

        contexts = [(c.source, c.page, c.text) for _, c in results]
        
        # Δημιουργία λίστας πηγών για εμφάνιση με scores
        sources = []
        seen = {}  # Αλλάζουμε σε dict για να κρατάμε το max score ανά πηγή
        
        for (score, chunk) in results:
            key = (chunk.source, chunk.page)
            # Κρατάμε το υψηλότερο score αν υπάρχουν πολλαπλά chunks από την ίδια πηγή/σελίδα
            if key not in seen or score > seen[key]:
                seen[key] = score
        
        # Δημιουργία της τελικής λίστας πηγών με scores
        for (source, page), score in seen.items():
            sources.append({
                "filename": source, 
                "page": page,
                "score": float(score)
            })
        
        # Ταξινόμηση πηγών με βάση το score (από υψηλότερο σε χαμηλότερο)
        sources.sort(key=lambda x: x["score"], reverse=True)
        
        # Κρατάμε μόνο τις top 2 πιο σχετικές πηγές για διασταύρωση
        sources = sources[:2]
        
        # Επιστροφή μόνο των αποσπασμάτων εάν δεν ζητηθεί χρήση AI
        if use_llm != "1":
            snippet = "\n\n".join([text for _, _, text in contexts])
            return {"ok": True, "answer": snippet, "sources": sources, "session_id": session_id}

        # Σύνθεση απάντησης με τη χρήση του μοντέλου γλώσσας
        messages = build_rag_prompt(question, contexts, extractive=(llm_extractive == "1"))
        answer, token_usage = chat(messages)
        
        prompt_text = "\n".join([msg["content"] for msg in messages])
        python_tokens = count_tokens_llama(prompt_text)
        api_prompt_tokens = token_usage["prompt_tokens"]
        difference = abs(python_tokens - api_prompt_tokens)
        percentage_diff = (difference / api_prompt_tokens * 100) if api_prompt_tokens > 0 else 0
        
        _log_add(f"Token comparison: Python={python_tokens}, API={api_prompt_tokens}, diff={difference} ({percentage_diff:.2f}%)")
        
        return {"ok": True, "answer": answer, "sources": sources, "session_id": session_id}

    except requests.exceptions.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", 502) or 502
        if status == 429:
            msg = "Rate limit exceeded (429). Please try again later."
        elif status in (401, 403):
            msg = "Insufficient permissions (401/403)."
        else:
            msg = f"Upstream error ({status})."
        return JSONResponse({"ok": False, "error": msg, "session_id": session_id}, status_code=status)
    except Exception as e:
        import traceback
        error_msg = str(e)
        tb = traceback.format_exc()
        _log_add(f"Query error: {error_msg}")
        _log_add(f"Traceback: {tb}")
        print(f"ERROR in query_pdf: {error_msg}", file=sys.stderr)
        print(tb, file=sys.stderr)
        return JSONResponse({"ok": False, "error": "Server error while searching.", "session_id": session_id}, status_code=500)


# Ανάκτηση στατιστικών στοιχείων χρήσης της συνεδρίας
@app.get("/sessions/{session_id}/stats")
async def get_session_stats(session_id: str, x_session_key: Optional[str] = Header(default=None)):
    _ensure_dirs()
    session_id = _normalize_session_id(session_id)
    _claim_or_verify_session(session_id, x_session_key)
    
    try:
        index_path, meta_path = get_session_index_paths(session_id, create_if_missing=False)
        
        if not os.path.exists(meta_path):
            return JSONResponse({
                "ok": True,
                "session_id": session_id,
                "total_tokens": 0,
                "total_chunks": 0,
                "total_documents": 0,
                "remaining_budget": 200000,
                "documents": []
            })
        
        store = FaissStore(dim=1024, index_path=index_path, meta_path=meta_path)
        store.load()
        
        if not store.metadata:
            return JSONResponse({
                "ok": True,
                "session_id": session_id,
                "total_tokens": 0,
                "total_chunks": 0,
                "total_documents": 0,
                "remaining_budget": 200000,
                "documents": []
            })
        
        docs_stats = {}
        for chunk in store.metadata:
            source = chunk.source
            if source not in docs_stats:
                docs_stats[source] = {
                    "name": source,
                    "tokens": 0,
                    "chunks": 0,
                    "pages": set()
                }
            chunk_tokens = chunk.tokens if chunk.tokens > 0 else count_tokens_llama(chunk.text)
            docs_stats[source]["tokens"] += chunk_tokens
            docs_stats[source]["chunks"] += 1
            docs_stats[source]["pages"].add(chunk.page)
        
        documents = []
        total_tokens = 0
        for doc in docs_stats.values():
            doc_data = {
                "name": doc["name"],
                "tokens": doc["tokens"],
                "chunks": doc["chunks"],
                "pages": len(doc["pages"])
            }
            documents.append(doc_data)
            total_tokens += doc["tokens"]
        
        MAX_SESSION_TOKENS = 200000
        remaining_budget = max(0, MAX_SESSION_TOKENS - total_tokens)
        
        return JSONResponse({
            "ok": True,
            "session_id": session_id,
            "total_tokens": total_tokens,
            "total_chunks": len(store.metadata),
            "total_documents": len(documents),
            "remaining_budget": remaining_budget,
            "max_session_tokens": MAX_SESSION_TOKENS,
            "usage_percentage": (total_tokens / MAX_SESSION_TOKENS) * 100,
            "documents": documents
        })
    except Exception as e:
        import traceback
        print(f"ERROR in get_session_stats: {str(e)}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return JSONResponse({"ok": False, "error": "Server error while loading session stats."}, status_code=500)


# Επιστροφή της αρχικής σελίδας της εφαρμογής
@app.get("/")
async def root() -> FileResponse:
    return FileResponse("static/index.html")

@app.get("/ready")
async def ready():
    _ensure_dirs()
    return {"ok": True, "status": "ready"}

# Προβολή του αρχείου καταγραφής
@app.get("/log")
async def get_log() -> FileResponse:
    _ensure_dirs()
    if not os.path.exists(LOG_PATH):
        _log_reset()
    return FileResponse(LOG_PATH, media_type="text/plain; charset=utf-8", filename="flow_log.txt")

# Διαγραφή ολόκληρης της συνεδρίας και των δεδομένων της
@app.post("/sessions/remove")
async def remove_session(
    session_id: str = Form(..., description="Session ID to delete"),
    x_session_key: Optional[str] = Header(default=None)
):
    _ensure_dirs()
    try:
        session_id = _normalize_session_id(session_id)
        _claim_or_verify_session(session_id, x_session_key)
        session_dir = os.path.join(INDEX_DIR, f"session_{session_id}")
        index_path = os.path.join(session_dir, "index.faiss")
        meta_path = os.path.join(session_dir, "metadata.json")
        upload_dir = get_session_upload_dir(session_id, create_if_missing=False)
        
        removed_count = 0
        
        if os.path.exists(index_path) or os.path.exists(meta_path):
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        removed_count = len(data)
                except Exception:
                    pass
            
            for p in (index_path, meta_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
            
            try:
                if os.path.exists(session_dir) and not os.listdir(session_dir):
                    os.rmdir(session_dir)
            except Exception:
                pass

        try:
            if os.path.exists(upload_dir):
                shutil.rmtree(upload_dir)
        except Exception:
            pass
        
        chat_history_deleted = chat_history_store.delete_session(session_id)
        _delete_session_owner(session_id)
        
        return {
            "ok": True, 
            "removed_chunks": removed_count,
            "chat_history_deleted": chat_history_deleted
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Server error while deleting the session."}, status_code=500)


# Αφαίρεση συγκεκριμένου αρχείου από το ευρετήριο
@app.post("/index/remove")
async def remove_indexed_file(
    filename: str = Form(..., description="Filename to remove"),
    session_id: str = Form(default=None, description="Session ID"),
    x_session_key: Optional[str] = Header(default=None)
):
    _ensure_dirs()
    
    if not session_id:
        return JSONResponse({"ok": False, "error": "Session ID is required."}, status_code=400)
    
    session_id = _normalize_session_id(session_id)
    _claim_or_verify_session(session_id, x_session_key)

    try:
        session_upload_dir = get_session_upload_dir(session_id, create_if_missing=False)
        file_path = os.path.join(session_upload_dir, filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        json_path = os.path.join(session_upload_dir, f"{os.path.splitext(filename)[0]}.json")
        if os.path.exists(json_path):
            os.remove(json_path)
        if os.path.exists(session_upload_dir) and not os.listdir(session_upload_dir):
            os.rmdir(session_upload_dir)
    except Exception:
        pass

    index_path, meta_path = get_session_index_paths(session_id, create_if_missing=False)
    store = FaissStore(dim=1024, index_path=index_path, meta_path=meta_path)
    try:
        store.load()
        if not getattr(store, "metadata", []):
            return {"ok": True, "removed": False, "remaining_chunks": 0}

        remaining_chunks: List[Chunk] = [c for c in store.metadata if c.source != filename]
        if len(remaining_chunks) == len(store.metadata):
            return {"ok": True, "removed": False, "remaining_chunks": len(remaining_chunks)}

        if not remaining_chunks:
            for p in (index_path, meta_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
            session_dir = os.path.dirname(index_path)
            try:
                if os.path.exists(session_dir) and not os.listdir(session_dir):
                    os.rmdir(session_dir)
            except Exception:
                pass
            
            return {
                "ok": True, 
                "removed": True, 
                "remaining_chunks": 0
            }

        texts = [c.text for c in remaining_chunks]
        vectors = embed_texts(texts)
        new_store = FaissStore(dim=vectors.shape[1], index_path=index_path, meta_path=meta_path)
        new_store.add(vectors, remaining_chunks)
        new_store.save()
        
        return {
            "ok": True, 
            "removed": True, 
            "remaining_chunks": len(remaining_chunks)
        }
    except requests.exceptions.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", 502) or 502
        if status == 429:
            msg = "Rate limit exceeded (429). Please try again later."
        elif status in (401, 403):
            msg = "Insufficient permissions (401/403)."
        else:
            msg = f"Upstream error ({status})."
        return JSONResponse({"ok": False, "error": msg}, status_code=status)
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Server error while removing the file."}, status_code=500)


# Αποθήκευση του ιστορικού συνομιλίας
@app.post("/chat/history/save")
async def save_chat_history(
    session_id: str = Form(..., description="Session ID to save"),
    messages: str = Form(..., description="Chat messages as a JSON string"),
    title: str = Form(default=None, description="Chat title"),
    timestamp: int = Form(default=None, description="Creation timestamp"),
    x_session_key: Optional[str] = Header(default=None)
):
    try:
        session_id = _normalize_session_id(session_id)
        _claim_or_verify_session(session_id, x_session_key)
        messages_list = json.loads(messages)
        chat_history_store.save_messages(session_id, messages_list, title=title, timestamp=timestamp, owner_key=_require_session_key(x_session_key))
        return {"ok": True, "session_id": session_id, "message_count": len(messages_list)}
    except json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "Invalid JSON payload."}, status_code=400)
    except HTTPException as e:
        return JSONResponse({"ok": False, "error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Failed to save chat history."}, status_code=500)

# Φόρτωση του ιστορικού συνομιλίας μιας συνεδρίας
@app.get("/chat/history/load")
async def load_chat_history(session_id: str, x_session_key: Optional[str] = Header(default=None)):
    try:
        session_id = _normalize_session_id(session_id)
        _claim_or_verify_session(session_id, x_session_key)
        messages = chat_history_store.load_messages(session_id)
        return {"ok": True, "session_id": session_id, "messages": messages}
    except HTTPException as e:
        return JSONResponse({"ok": False, "error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Failed to load chat history."}, status_code=500)

@app.get("/chat/history/list")
async def list_chat_sessions(x_session_key: Optional[str] = Header(default=None)):
    try:
        sessions = chat_history_store.list_sessions(owner_key=_require_session_key(x_session_key))
        return {"ok": True, "sessions": sessions}
    except HTTPException as e:
        return JSONResponse({"ok": False, "error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Failed to load chat list."}, status_code=500)

@app.post("/chat/history/delete")
async def delete_chat_history(
    session_id: str = Form(..., description="Session ID to delete"),
    x_session_key: Optional[str] = Header(default=None)
):
    try:
        session_id = _normalize_session_id(session_id)
        _claim_or_verify_session(session_id, x_session_key)
        success = chat_history_store.delete_session(session_id)
        
        index_deleted = False
        try:
            session_dir = os.path.join(INDEX_DIR, f"session_{session_id}")
            index_path = os.path.join(session_dir, "index.faiss")
            meta_path = os.path.join(session_dir, "metadata.json")
            upload_dir = get_session_upload_dir(session_id, create_if_missing=False)
            if os.path.exists(index_path) or os.path.exists(meta_path):
                for p in (index_path, meta_path):
                    if os.path.exists(p):
                        os.remove(p)
                
                session_dir = os.path.dirname(index_path)
                if os.path.exists(session_dir) and not os.listdir(session_dir):
                    os.rmdir(session_dir)
                
                index_deleted = True
            if os.path.exists(upload_dir):
                shutil.rmtree(upload_dir)
        except Exception as e:
            _log_add(f"Warning: Failed to delete index for session '{session_id}': {e}")
        _delete_session_owner(session_id)
        
        if success:
            return {
                "ok": True, 
                "session_id": session_id, 
                "deleted": True,
                "index_deleted": index_deleted
            }
        else:
            return {"ok": True, "session_id": session_id, "deleted": False, "message": "Chat history was not found."}
    except HTTPException as e:
        return JSONResponse({"ok": False, "error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Failed to delete chat history."}, status_code=500)
