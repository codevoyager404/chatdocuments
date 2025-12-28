# Εισαγωγή βιβλιοθηκών για τη διαχείριση συστήματος και αρχείων
import os
import sys
import locale
import uuid
import shutil
from datetime import datetime
from typing import List, Optional, Tuple
import json

# Ρύθμιση για τη σωστή εμφάνιση ελληνικών χαρακτήρων σε περιβάλλον Windows
if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

# Ορισμός τοπικών ρυθμίσεων γλώσσας για την υποστήριξη Ελληνικών
try:
    locale.setlocale(locale.LC_ALL, 'el_GR.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'C.UTF-8')
    except locale.Error:
        pass

# Εισαγωγή εργαλείων για τη δημιουργία της διαδικτυακής εφαρμογής (Web API)
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, FileResponse

# Εισαγωγή των απαραίτητων μονάδων για την επεξεργασία AI και εγγράφων
from .cf_ai import embed_texts, chat, build_rag_prompt, count_tokens_llama, validate_token_budget, calculate_optimal_k
import requests
from .index_store import Chunk, FaissStore
from .pdf_utils import extract_pdf_text_with_pages, chunk_text
from .pptx_utils import extract_pptx_text_with_slides
from .file_utils import safe_filename
from .chat_history import ChatHistoryStore

# Μέγιστο επιτρεπόμενο μέγεθος αρχείου (50MB)
MAX_BYTES = 50 * 1024 * 1024

# Διαχείριση σφαλμάτων κατά την επεξεργασία εγγράφων
class FileIngestError(Exception):
    def __init__(self, reason: str, stage: str): 
        super().__init__(reason)
        self.reason = reason
        self.stage = stage

# Καθορισμός διαδρομών για την αποθήκευση δεδομένων και ιστορικού
DATA_DIR = "./data"
INDEX_DIR = os.path.join(DATA_DIR, "index")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
LOG_DIR = os.path.join(DATA_DIR, "logs")
CHAT_HISTORY_DIR = os.path.join(DATA_DIR, "chat_history")
LOG_PATH = os.path.join(LOG_DIR, "flow_log.txt")

# Εντοπισμός των αρχείων δεδομένων για μια συγκεκριμένη συνεδρία
def get_session_index_paths(session_id: str, create_if_missing: bool = False) -> Tuple[str, str]:
    session_dir = os.path.join(INDEX_DIR, f"session_{session_id}")
    if create_if_missing:
        os.makedirs(session_dir, exist_ok=True)
    index_path = os.path.join(session_dir, "index.faiss")
    meta_path = os.path.join(session_dir, "metadata.json")
    return index_path, meta_path

# Αρχικοποίηση της εφαρμογής FastAPI
app = FastAPI(title="Chat PDF - Ελληνική Έκδοση")

# Ρύθμιση CORS για την επικοινωνία μεταξύ Frontend και Backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Σύνδεση φακέλου στατικών αρχείων για τη διεπαφή χρήστη
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Εξασφάλιση ύπαρξης των απαραίτητων φακέλων στο σύστημα
def _ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(INDEX_DIR, exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(CHAT_HISTORY_DIR, exist_ok=True)

# Απενεργοποίηση προσωρινής αποθήκευσης για τα στατικά αρχεία
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

# Δημιουργία νέου αρχείου καταγραφής ενεργειών
def _log_reset() -> None:
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"[#] Νέα συνεδρία: {datetime.now().isoformat(timespec='seconds')}\n")
    except Exception:
        pass

# Προσθήκη νέας καταγραφής με χρονοσήμανση
def _log_add(line: str) -> None:
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
    except Exception:
        pass

# Επεξεργασία αρχείου: μεταφόρτωση, εξαγωγή κειμένου και κατάτμηση
async def _process_one_file(up: UploadFile, session_id: str) -> Tuple[List[Chunk], List[str], str, dict]:
    original_filename = up.filename or f'file_{uuid.uuid4().hex}'
    original_ext = os.path.splitext(original_filename)[1].lower()
    base_name = safe_filename(original_filename)
    
    if not base_name.endswith(original_ext) and original_ext:
        original_name = base_name + original_ext
    else:
        original_name = base_name
    
    saved_file_path = os.path.join(UPLOADS_DIR, original_name)
    tmp_path = os.path.join(UPLOADS_DIR, f"upload_{uuid.uuid4().hex}_{original_name}")

    bytes_written = 0
    try:
        # Αποθήκευση του αρχείου στο δίσκο
        with open(tmp_path, "wb") as fout:
            while True:
                chunk = await up.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > MAX_BYTES:
                    raise FileIngestError("Πολύ μεγάλο αρχείο", "upload")
                fout.write(chunk)
        await up.close()
        
        if bytes_written == 0:
            raise FileIngestError("Άδειο αρχείο", "upload")

        # Εξαγωγή περιεχομένου ανάλογα με τον τύπο του αρχείου
        ext = original_ext if original_ext else os.path.splitext(original_name)[1].lower()
        if ext == ".pdf":
            pairs = extract_pdf_text_with_pages(tmp_path)
        elif ext == ".pptx":
            pairs = extract_pptx_text_with_slides(tmp_path)
        else:
            ext_display = ext if ext else "(χωρίς κατάληξη)"
            _log_add(f"Σφάλμα: Μη υποστηριζόμενος τύπος '{ext_display}' για το αρχείο '{original_filename}'")
            raise FileIngestError(
                f"Μη υποστηριζόμενος τύπος αρχείου: '{ext_display}'. "
                f"Υποστηριζόμενοι τύποι: .pdf, .pptx. Αρχικό όνομα αρχείου: '{original_filename}'",
                "validate"
            )

        # Έλεγχος μεγέθους εγγράφου σε tokens
        full_text = "\n\n".join([text for _, text in pairs if text.strip()])
        total_tokens = count_tokens_llama(full_text)
        MAX_TOKENS_PER_FILE = 50000
        
        if total_tokens > MAX_TOKENS_PER_FILE:
            raise FileIngestError(
                f"Το έγγραφο είναι πολύ μεγάλο (~{total_tokens:,} tokens). "
                f"Μέγιστο όριο: {MAX_TOKENS_PER_FILE:,} tokens. "
                f"Παρακαλώ χωρίστε το έγγραφο σε μικρότερα τμήματα.",
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
        json_path = os.path.join(UPLOADS_DIR, f"{os.path.splitext(original_name)[0]}.json")
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
    manifest: Optional[str] = Form(default=None, description="Λίστα αναμενόμενων αρχείων σε μορφή JSON")
):
    _ensure_dirs()
    
    inputs: List[UploadFile] = []
    if files:
        inputs.extend(files)
    if file:
        inputs.append(file)
    if not inputs:
        return JSONResponse({"ok": False, "error": "Δεν επιλέχθηκαν αρχεία.", "session_id": session_id}, status_code=400)

    if not session_id:
        session_id = str(uuid.uuid4())

    expected = set()
    if manifest:
        try:
            expected = set(json.loads(manifest))
        except Exception:
            return JSONResponse({"ok": False, "error": "Μη έγκυρο manifest.", "session_id": session_id}, status_code=400)

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
            failures.append({"name": up.filename or "Άγνωστο", "reason": e.reason, "stage": e.stage})
        except Exception as e:
            failures.append({"name": up.filename or "Άγνωστο", "reason": f"Απροσδόκητο σφάλμα: {str(e)}", "stage": "άγνωστο"})

    received_names = {p["name"] for p in processed} | {f["name"] for f in failures}
    missing = [n for n in expected if n not in received_names]
    failures.extend({"name": n, "reason": "Δεν παραλήφθηκε", "stage": "upload"} for n in missing)

    if strict and failures:
        return JSONResponse({"ok": False, "mode": "strict", "processed": processed, "failed": failures, "session_id": session_id}, status_code=409)

    if not all_texts:
        if failures:
            error_msg = "Δεν υπάρχουν έγκυρα έγγραφα. "
            if len(failures) == 1:
                error_msg += f"Το αρχείο '{failures[0]['name']}' απέτυχε: {failures[0].get('reason', 'Άγνωστο σφάλμα')}"
            else:
                error_msg += f"{len(failures)} αρχεία απέτυχαν. Κάντε κλικ στο κουμπί ℹ για λεπτομέρειες."
        else:
            error_msg = "Δεν υπάρχουν έγκυρα έγγραφα."
        
        try:
            session_dir = os.path.dirname(index_path)
            if os.path.exists(session_dir) and not os.listdir(session_dir):
                os.rmdir(session_dir)
                _log_add(f"Καθαρισμός κενού καταλόγου συνεδρίας: {session_dir}")
        except Exception as cleanup_error:
            _log_add(f"Προειδοποίηση: Αποτυχία καθαρισμού καταλόγου συνεδρίας: {cleanup_error}")
        
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
            msg = "Όριο ταχύτητας (429). Περιμένετε λίγο και ξαναδοκιμάστε."
        elif status in (401, 403):
            msg = "Ανεπαρκή δικαιώματα (401/403)."
        else:
            msg = f"Σφάλμα upstream ({status})."
        _log_add(f"Σφάλμα HTTP: {msg}")
        return JSONResponse({"ok": False, "error": msg, "processed": processed, "failed": failures, "session_id": session_id}, status_code=status)
    except Exception as e:
        import traceback
        error_msg = str(e)
        tb = traceback.format_exc()
        _log_add(f"Σφάλμα διακομιστή: {error_msg}")
        _log_add(f"Traceback: {tb}")
        print(f"ERROR in index_files: {error_msg}", file=sys.stderr)
        print(tb, file=sys.stderr)
        
        try:
            session_dir = os.path.dirname(index_path)
            if os.path.exists(session_dir) and not os.path.exists(index_path) and not os.path.exists(meta_path):
                if not os.listdir(session_dir):
                    os.rmdir(session_dir)
                    _log_add(f"Καθαρισμός κενού καταλόγου συνεδρίας μετά από σφάλμα: {session_dir}")
        except Exception as cleanup_error:
            _log_add(f"Προειδοποίηση: Αποτυχία καθαρισμού καταλόγου συνεδρίας: {cleanup_error}")
        
        return JSONResponse({"ok": False, "error": f"Σφάλμα διακομιστή: {error_msg}", "processed": processed, "failed": failures, "session_id": session_id}, status_code=500)

# Υποβολή ερωτήματος και λήψη απάντησης από το μοντέλο AI
@app.post("/query")
async def query_pdf(
    question: str = Form(..., description="Η ερώτηση του χρήστη προς τα έγγραφα"),
    k: int = Form(5, description="Αριθμός κομματιών κειμένου (chunks) προς ανάκτηση"),
    use_llm: str = Form("1", description="Χρήση LLM για απάντηση (1=Ναι, 0=Όχι)"),
    llm_extractive: str = Form("0", description="Λειτουργία εξόρυξης κειμένου (Extractive Mode)"),
    session_id: str = Form(default=None, description="Το ID της τρέχουσας συνεδρίας")
):
    _ensure_dirs()

    if not session_id:
        return JSONResponse({
            "ok": False,
            "error": "Δεν υπάρχει ενεργή συνεδρία. Ξεκινήστε νέα για να συνεχίσετε."
        }, status_code=400)

    if not (question or "").strip():
        return JSONResponse({"ok": False, "error": "Η ερώτηση δεν μπορεί να είναι κενή."}, status_code=400)

    index_path, meta_path = get_session_index_paths(session_id, create_if_missing=False)
    store = FaissStore(dim=1024, index_path=index_path, meta_path=meta_path)
    try:
        store.load()

        if not store.metadata:
            return JSONResponse({
                "ok": False,
                "error": "Δεν έχουν ανέβει ακόμα έγγραφα. Ανεβάστε ένα PDF ή PowerPoint."
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
            _log_add(f"Δυναμικός υπολογισμός k: χρήση k={k} (σύνολο_chunks={total_chunks}, σελίδες={total_pages})")

        # Μετατροπή ερώτησης σε διάνυσμα και αναζήτηση σχετικών τμημάτων
        q_vec = embed_texts([question])[0]
        _log_add(f"Ερώτηση: '{question}' | k={k} | use_llm={use_llm} | extractive={llm_extractive} | session_id={session_id}")

        results = store.search(q_vec, k=k)
        try:
            for rank, (score, c) in enumerate(results, start=1):
                _log_add(f"Κορυφαίο{rank}: πηγή='{c.source}', σελίδα={c.page}, score={score:.4f}")
        except Exception:
            pass

        if not results:
            return JSONResponse({
                "ok": False,
                "error": "Δεν βρέθηκαν σχετικά αποσπάσματα για αυτή την ερώτηση.",
                "session_id": session_id
            }, status_code=400)

        contexts = [(c.source, c.page, c.text) for _, c in results]
        
        # Επιστροφή μόνο των αποσπασμάτων εάν δεν ζητηθεί χρήση AI
        if use_llm != "1":
            snippet = "\n\n".join([text for _, _, text in contexts])
            return {"ok": True, "answer": snippet, "session_id": session_id}

        # Σύνθεση απάντησης με τη χρήση του μοντέλου γλώσσας
        messages = build_rag_prompt(question, contexts, extractive=(llm_extractive == "1"))
        answer, token_usage = chat(messages)
        
        prompt_text = "\n".join([msg["content"] for msg in messages])
        python_tokens = count_tokens_llama(prompt_text)
        api_prompt_tokens = token_usage["prompt_tokens"]
        difference = abs(python_tokens - api_prompt_tokens)
        percentage_diff = (difference / api_prompt_tokens * 100) if api_prompt_tokens > 0 else 0
        
        _log_add(f"Σύγκριση tokens: Python={python_tokens}, API={api_prompt_tokens}, διαφορά={difference} ({percentage_diff:.2f}%)")
        
        return {"ok": True, "answer": answer, "session_id": session_id}

    except requests.exceptions.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", 502) or 502
        if status == 429:
            msg = "Όριο ταχύτητας (429). Ξαναδοκιμάστε μετά."
        elif status in (401, 403):
            msg = "Ανεπαρκή δικαιώματα (401/403)."
        else:
            msg = f"Σφάλμα upstream ({status})."
        return JSONResponse({"ok": False, "error": msg, "session_id": session_id}, status_code=status)
    except Exception as e:
        import traceback
        error_msg = str(e)
        tb = traceback.format_exc()
        _log_add(f"Σφάλμα σε query_pdf: {error_msg}")
        _log_add(f"Traceback: {tb}")
        print(f"ERROR in query_pdf: {error_msg}", file=sys.stderr)
        print(tb, file=sys.stderr)
        return JSONResponse({"ok": False, "error": "Σφάλμα διακομιστή κατά την αναζήτηση.", "session_id": session_id}, status_code=500)


# Ανάκτηση στατιστικών στοιχείων χρήσης της συνεδρίας
@app.get("/sessions/{session_id}/stats")
async def get_session_stats(session_id: str):
    _ensure_dirs()
    
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
        return JSONResponse({"ok": False, "error": "Σφάλμα διακομιστή κατά την ανάκτηση στατιστικών."}, status_code=500)


# Επιστροφή της αρχικής σελίδας της εφαρμογής
@app.get("/")
async def root() -> FileResponse:
    return FileResponse("static/index.html")

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
    session_id: str = Form(..., description="Το ID της συνεδρίας προς διαγραφή")
):
    _ensure_dirs()
    try:
        session_dir = os.path.join(INDEX_DIR, f"session_{session_id}")
        index_path = os.path.join(session_dir, "index.faiss")
        meta_path = os.path.join(session_dir, "metadata.json")
        
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
        
        chat_history_deleted = chat_history_store.delete_session(session_id)
        
        return {
            "ok": True, 
            "removed_chunks": removed_count,
            "chat_history_deleted": chat_history_deleted
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Σφάλμα διακομιστή κατά τη διαγραφή συνεδρίας."}, status_code=500)


# Αφαίρεση συγκεκριμένου αρχείου από το ευρετήριο
@app.post("/index/remove")
async def remove_indexed_file(
    filename: str = Form(..., description="Το όνομα του αρχείου προς διαγραφή"),
    session_id: str = Form(default=None, description="Το ID της συνεδρίας")
):
    _ensure_dirs()
    
    if not session_id:
        return JSONResponse({"ok": False, "error": "Session ID απαιτείται."}, status_code=400)
    
    try:
        file_path = os.path.join(UPLOADS_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        
        json_path = os.path.join(UPLOADS_DIR, f"{os.path.splitext(filename)[0]}.json")
        if os.path.exists(json_path):
            os.remove(json_path)
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
            msg = "Όριο ταχύτητας (429). Ξαναδοκιμάστε μετά."
        elif status in (401, 403):
            msg = "Ανεπαρκή δικαιώματα (401/403)."
        else:
            msg = f"Σφάλμα upstream ({status})."
        return JSONResponse({"ok": False, "error": msg}, status_code=status)
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Σφάλμα διακομιστή κατά την αφαίρεση αρχείου."}, status_code=500)


# Αποθήκευση του ιστορικού συνομιλίας
@app.post("/chat/history/save")
async def save_chat_history(
    session_id: str = Form(..., description="Το ID της συνεδρίας για αποθήκευση"),
    messages: str = Form(..., description="Τα μηνύματα της συνομιλίας σε μορφή JSON string"),
    title: str = Form(default=None, description="Ο τίτλος της συνομιλίας"),
    timestamp: int = Form(default=None, description="Timestamp δημιουργίας")
):
    try:
        messages_list = json.loads(messages)
        chat_history_store.save_messages(session_id, messages_list, title=title, timestamp=timestamp)
        return {"ok": True, "session_id": session_id, "message_count": len(messages_list)}
    except json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "Μη έγκυρα δεδομένα JSON."}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Σφάλμα κατά την αποθήκευση ιστορικού."}, status_code=500)

# Φόρτωση του ιστορικού συνομιλίας μιας συνεδρίας
@app.get("/chat/history/load")
async def load_chat_history(session_id: str):
    try:
        messages = chat_history_store.load_messages(session_id)
        return {"ok": True, "session_id": session_id, "messages": messages}
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Σφάλμα κατά τη φόρτωση ιστορικού."}, status_code=500)

@app.get("/chat/history/list")
async def list_chat_sessions():
    try:
        sessions = chat_history_store.list_sessions()
        return {"ok": True, "sessions": sessions}
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Σφάλμα κατά την ανάκτηση λίστας."}, status_code=500)

@app.post("/chat/history/delete")
async def delete_chat_history(
    session_id: str = Form(..., description="Το ID της συνεδρίας προς διαγραφή")
):
    try:
        success = chat_history_store.delete_session(session_id)
        
        index_deleted = False
        try:
            session_dir = os.path.join(INDEX_DIR, f"session_{session_id}")
            index_path = os.path.join(session_dir, "index.faiss")
            meta_path = os.path.join(session_dir, "metadata.json")
            if os.path.exists(index_path) or os.path.exists(meta_path):
                for p in (index_path, meta_path):
                    if os.path.exists(p):
                        os.remove(p)
                
                session_dir = os.path.dirname(index_path)
                if os.path.exists(session_dir) and not os.listdir(session_dir):
                    os.rmdir(session_dir)
                
                index_deleted = True
        except Exception as e:
            _log_add(f"Προειδοποίηση: Αποτυχία διαγραφής index για session '{session_id}': {e}")
        
        if success:
            return {
                "ok": True, 
                "session_id": session_id, 
                "deleted": True,
                "index_deleted": index_deleted
            }
        else:
            return {"ok": True, "session_id": session_id, "deleted": False, "message": "Δεν βρέθηκε ιστορικό."}
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Σφάλμα κατά τη διαγραφή ιστορικού."}, status_code=500)