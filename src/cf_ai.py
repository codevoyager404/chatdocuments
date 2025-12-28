import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests
from dotenv import load_dotenv


# Ορισμός μοντέλων Cloudflare AI.
EMBEDDING_MODEL = "@cf/baai/bge-m3"
LLM_MODEL = "@cf/meta/llama-3.1-8b-instruct-fp8"  # Χρήση FP8 quantized μοντέλου με 32K context window.


def _require_env(name: str) -> str:
    # Ελέγχει την ύπαρξη μιας μεταβλητής περιβάλλοντος και εγείρει σφάλμα αν λείπει.
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Λείπει η απαιτούμενη μεταβλητή περιβάλλοντος: {name}")
    return value


def _cf_request(model: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Εκτελεί HTTP POST αίτημα στο Cloudflare AI API.
    load_dotenv(override=False)
    account_id = _require_env("CLOUDFLARE_ACCOUNT_ID")
    api_token = _require_env("CLOUDFLARE_API_TOKEN")

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Η αίτηση στο {model} άργησε πολύ (timeout).")
    except requests.exceptions.HTTPError as e:
        # Προσπάθεια εξαγωγής λεπτομερούς μηνύματος σφάλματος από την απάντηση JSON.
        error_msg = str(e)
        try:
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    if 'errors' in error_detail and error_detail['errors']:
                        error_msg = error_detail['errors'][0].get('message', str(e))
                    elif 'error' in error_detail:
                        error_msg = str(error_detail['error'])
                    else:
                        error_msg = f"{str(e)} - Response: {error_detail}"
                except:
                    # Αν αποτύχει η ανάλυση JSON, χρησιμοποιώ το κείμενο της απόκρισης.
                    error_msg = f"{str(e)} - Response: {e.response.text[:500]}"
        except Exception:
            pass
        raise RuntimeError(f"API error προς το {model}: {error_msg}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"API error προς το {model}: {str(e)}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Η απόκριση από το {model} δεν ήταν έγκυρο JSON: {str(e)}")


def _extract_vectors_from_response(container) -> List[List[float]]:
    # Εξάγει τα embeddings από τη δομή απόκρισης του Cloudflare API.
    vectors: List[List[float]] = []
    if isinstance(container, dict):
        if "data" in container:
            data = container["data"]
            if data and isinstance(data[0], dict) and "embedding" in data[0]:
                vectors = [row["embedding"] for row in data]
            else:
                vectors = data
        elif "embeddings" in container:
            vectors = container["embeddings"]
    elif isinstance(container, list):
        # Σε ορισμένες περιπτώσεις, το API επιστρέφει λίστα απευθείας.
        vectors = container
    return vectors


def _estimate_tokens(text: str) -> int:
    # Υπολογίζει προσεγγιστικά τα tokens διαιρώντας τους χαρακτήρες διά 4.
    return len(text) // 4


def count_tokens_llama(text: str) -> int:
    # Υπολογίζει τον ακριβή αριθμό tokens χρησιμοποιώντας το tiktoken, αν είναι διαθέσιμο.
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except ImportError:
        # Χρήση προσεγγιστικής μεθόδου αν λείπει η βιβλιοθήκη tiktoken.
        return _estimate_tokens(text)
    except Exception:
        return _estimate_tokens(text)


def validate_token_budget(
    new_document_tokens: int,
    existing_session_tokens: int = 0,
    max_per_document: int = 50000,
    max_per_session: int = 200000
) -> Tuple[bool, Optional[str], Dict[str, int]]:
    # Ελέγχει αν η προσθήκη νέου εγγράφου παραβιάζει τα όρια tokens ανά έγγραφο ή ανά συνεδρία.
    details = {
        "new_document_tokens": new_document_tokens,
        "existing_session_tokens": existing_session_tokens,
        "total_after": existing_session_tokens + new_document_tokens,
        "max_per_document": max_per_document,
        "max_per_session": max_per_session,
    }
    
    # Έλεγχος ορίου ανά έγγραφο.
    if new_document_tokens > max_per_document:
        percentage_over = ((new_document_tokens - max_per_document) / max_per_document) * 100
        error = (
            f"Το έγγραφο είναι πολύ μεγάλο (~{new_document_tokens:,} tokens). "
            f"Μέγιστο όριο: {max_per_document:,} tokens. "
            f"Υπέρβαση: {percentage_over:.1f}%. "
            f"Παρακαλώ χωρίστε το έγγραφο σε μικρότερα τμήματα."
        )
        return False, error, details
    
    # Έλεγχος ορίου ανά συνεδρία.
    total_after = existing_session_tokens + new_document_tokens
    if total_after > max_per_session:
        remaining = max_per_session - existing_session_tokens
        error = (
            f"Υπέρβαση ορίου tokens για τη συνεδρία. "
            f"Τρέχοντα: {existing_session_tokens:,}, Νέο: {new_document_tokens:,}, "
            f"Σύνολο: {total_after:,} (όριο: {max_per_session:,}). "
            f"Διαθέσιμα: {remaining:,} tokens. "
            f"Διαγράψτε παλιά έγγραφα ή ξεκινήστε νέα συνεδρία."
        )
        return False, error, details
    
    return True, None, details


def calculate_optimal_k(
    total_chunks: int,
    total_tokens: int = 0,
    max_context_tokens: int = 28000
) -> int:
    # Υπολογίζει δυναμικά τον βέλτιστο αριθμό chunks (k) προς ανάκτηση.
    # Στόχος είναι η μέγιστη αξιοποίηση του context window χωρίς απώλεια πληροφορίας.
    
    # Για μικρά έγγραφα (≤10K tokens), προσπαθούμε να καλύψουμε το 100%.
    if total_tokens > 0 and total_tokens <= 10000:
        if total_chunks > 0:
            avg_tokens_per_chunk = total_tokens / total_chunks
            available_tokens = max_context_tokens - 4000
            max_k_by_tokens = max(8, int(available_tokens / avg_tokens_per_chunk))
            
            if total_chunks <= max_k_by_tokens:
                return min(total_chunks, 25)
            return min(max_k_by_tokens, 25)
        return min(total_chunks, 25)
    
    # Για μεγαλύτερα έγγραφα, αυξάνουμε σταδιακά το k.
    if total_tokens > 0:
        if total_tokens <= 30000:
            suggested_k = 15
        elif total_tokens <= 50000:
            suggested_k = 18
        else:
            suggested_k = 25
    else:
        # Fallback λογική αν δεν υπάρχουν πληροφορίες για tokens.
        if total_chunks <= 20:
            suggested_k = min(total_chunks, 25)
        elif total_chunks <= 40:
            suggested_k = 15
        elif total_chunks <= 60:
            suggested_k = 18
        else:
            suggested_k = 25
    
    # Τελικός έλεγχος ώστε να μην ξεπεραστεί το context window.
    if total_tokens > 0 and total_chunks > 0:
        avg_tokens_per_chunk = total_tokens / total_chunks
        available_tokens = max_context_tokens - 4000
        max_k_by_tokens = max(8, int(available_tokens / avg_tokens_per_chunk))
        suggested_k = min(suggested_k, max_k_by_tokens)
    
    # Επιβολή ορίων: ελάχιστο 8, μέγιστο 25 chunks.
    optimal_k = max(8, min(suggested_k, 25, total_chunks))
    
    return optimal_k

def embed_texts(texts: List[str], batch_size: int = None, max_tokens_per_batch: int = 50000) -> np.ndarray:
    # Μετατρέπει μια λίστα κειμένων σε embeddings, χωρίζοντάς τα σε batches για το API.
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)

    if not isinstance(texts, list):
        raise ValueError("Πρέπει να περάσεις λίστα από strings.")

    valid_texts = [t for t in texts if isinstance(t, str) and t.strip()]
    if not valid_texts:
        return np.zeros((0, 0), dtype=np.float32)

    # Υπολογισμός μεγέθους batch αν δεν έχει οριστεί.
    if batch_size is None:
        sample_size = min(10, len(valid_texts))
        avg_tokens = sum(_estimate_tokens(t) for t in valid_texts[:sample_size]) / sample_size if valid_texts else 0
        
        # Χρήση συντελεστή ασφαλείας 0.7 για αποφυγή υπέρβασης ορίου.
        calculated_batch_size = max(1, int((max_tokens_per_batch * 0.7) / avg_tokens) if avg_tokens > 0 else 20)
        
        # Επιβολή ορίων batch size.
        batch_size = min(calculated_batch_size, 40)
        batch_size = max(batch_size, 20)

    try:
        # Διαχωρισμός σε batches με βάση τον αριθμό tokens.
        all_vectors = []
        current_batch = []
        current_tokens = 0
        
        for text in valid_texts:
            text_tokens = _estimate_tokens(text)
            
            # Έλεγχος αν το τρέχον batch πρέπει να σταλεί.
            should_send = False
            if current_batch and (current_tokens + text_tokens > max_tokens_per_batch or len(current_batch) >= batch_size):
                should_send = True
            
            if should_send:
                # Αποστολή του τρέχοντος batch στο API.
                raw = _cf_request(EMBEDDING_MODEL, {"text": current_batch})
                container = raw.get("result", raw)
                batch_vectors = _extract_vectors_from_response(container)
                all_vectors.extend(batch_vectors)
                
                current_batch = []
                current_tokens = 0
            
            current_batch.append(text)
            current_tokens += text_tokens
            
            # Παράλειψη κειμένου αν υπερβαίνει μόνο του το όριο tokens.
            if text_tokens > max_tokens_per_batch:
                current_batch.pop()
                current_tokens -= text_tokens
                print(f"Warning: Text too large ({text_tokens} tokens), skipping...", file=sys.stderr)
        
        # Αποστολή του τελευταίου batch που απέμεινε.
        if current_batch:
            raw = _cf_request(EMBEDDING_MODEL, {"text": current_batch})
            container = raw.get("result", raw)
            batch_vectors = _extract_vectors_from_response(container)
            all_vectors.extend(batch_vectors)
        
        vectors = all_vectors

        if not vectors:
            raise RuntimeError("Το API δεν έδωσε embeddings.")

        arr = np.array(vectors, dtype=np.float32)
        if arr.ndim != 2 or arr.size == 0:
            raise RuntimeError("Λάθος μορφή embeddings από το API.")

        # Εφαρμογή L2 κανονικοποίησης για χρήση με Cosine Similarity.
        norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12
        return arr / norms

    except Exception as e:
        raise RuntimeError(f"Σφάλμα στον υπολογισμό embeddings: {str(e)}")


def chat(messages: List[Dict[str, str]]) -> Tuple[str, Dict[str, int]]:
    # Στέλνει μια συνομιλία στο LLM και επιστρέφει την απάντηση και τη χρήση tokens.
    if not messages:
        raise ValueError("Η λίστα μηνυμάτων είναι άδεια.")

    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise ValueError(f"Το μήνυμα {i} δεν είναι dict.")
        if "role" not in msg or "content" not in msg:
            raise ValueError(f"Το μήνυμα {i} δεν έχει role/content.")
        if not isinstance(msg["content"], str):
            raise ValueError(f"Το content του {i} πρέπει να είναι string.")

    try:
        raw = _cf_request(LLM_MODEL, {"messages": messages})
        container = raw.get("result", raw)

        text = (
            container.get("response")
            or container.get("text")
            or container.get("result")
        )

        # Εξαγωγή στατιστικών χρήσης tokens από το API.
        usage = container.get("usage", {})
        token_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0)
        }

        if not text:
            # Αν η απάντηση είναι κενή, ελέγχω αν οφείλεται σε υπέρβαση ορίου tokens.
            prompt_tokens = token_usage["prompt_tokens"]
            completion_tokens = token_usage["completion_tokens"]
            
            if prompt_tokens > 30000 and completion_tokens == 0:
                raise RuntimeError(
                    f"Το prompt είναι πολύ μεγάλο ({prompt_tokens} tokens). "
                    f"Το LLM δεν μπόρεσε να απαντήσει. Προσπαθήστε με μικρότερη ερώτηση ή λιγότερα αποσπάσματα."
                )
            raise RuntimeError(f"Άδεια/άκυρη απόκριση από LLM: {json.dumps(raw)[:500]}")

        return str(text).strip(), token_usage
    except Exception as e:
        raise RuntimeError(f"Σφάλμα στο chat με LLM: {str(e)}")


def build_rag_prompt(
    question: str,
    contexts: List[Tuple[str, int, str]],
    extractive: bool = False,
    max_context_tokens: int = 28000,
) -> List[Dict[str, str]]:
    # Κατασκευάζει το prompt για το σύστημα RAG, επιλέγοντας τον κατάλληλο ρόλο συστήματος.
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Η ερώτηση πρέπει να είναι string με περιεχόμενο.")

    if not isinstance(contexts, list):
        raise ValueError("Τα contexts πρέπει να είναι λίστα.")

    valid_contexts: List[Tuple[str, int, str]] = []
    for i, ctx in enumerate(contexts):
        if not isinstance(ctx, tuple) or len(ctx) != 3:
            raise ValueError(f"Το context {i} πρέπει να είναι (source, page, text).")
        src, page, text = ctx
        if isinstance(text, str) and text.strip():
            valid_contexts.append((src, page, text.strip()))

    # Περικοπή των κειμένων αν υπερβαίνουν το όριο context.
    # Χρησιμοποιώ έναν συντηρητικό υπολογισμό (3 chars/token).
    total_chars = 0
    truncated_contexts = []
    max_chars = max_context_tokens * 3
    
    for src, page, text in valid_contexts:
        text_chars = len(text)
        if total_chars + text_chars > max_chars:
            # Περικοπή κειμένου ώστε να τηρηθεί το όριο.
            remaining_chars = max(0, max_chars - total_chars - 200)
            if remaining_chars > 200:
                truncated_text = text[:remaining_chars] + "... [κομμένο]"
                truncated_contexts.append((src, page, truncated_text))
            break
        truncated_contexts.append((src, page, text))
        total_chars += text_chars

    context_block = "\n\n".join([t for _, _, t in truncated_contexts])

    if extractive:
        system = (
            "Είσαι βοηθός extractive. Απαντάς μόνο με αυτούσια αποσπάσματα "
            "χωρίς παραφράσεις. "
            "ΣΗΜΑΝΤΙΚΟ: Κάνε ευέλικτη αναζήτηση - αν η ερώτηση αναφέρεται σε κάτι συγκεκριμένο "
            "(ημερομηνία, αριθμό, όρο), αναζήτησε και για παρόμοιες ή συναφείς φράσεις. "
            "Αν βρεις ΟΠΟΙΑΔΗΠΟΤΕ σχετική πληροφορία, επέστρεψε το ακριβές απόσπασμα. "
            "ΜΟΝΟ αν ΠΡΑΓΜΑΤΙΚΑ δεν υπάρχει τίποτα σχετικό, πες "
            "«Δεν βρέθηκε σχετικό απόσπασμα στο παρεχόμενο.»"
        )
    else:
        system = (
        "Είσαι βοηθός που απαντά με βάση τα αποσπάσματα. "
        "Δίνεις ΜΙΑ ξεκάθαρη και πλήρη απάντηση. "
        "\n"
        "ΚΑΝΟΝΕΣ: "
        "1. Απάντησε ΜΟΝΟ ΜΙΑ ΦΟΡΑ. ΜΗΝ επαναλάβεις την απάντηση με διαφορετική μορφή. "
        "2. ΜΗΝ χρησιμοποιήσεις τίτλους όπως 'Απαντήσεις:', 'Συμπέρασμα:', ή παρόμοια. "
        "3. Κάνε ευέλικτη και προσεκτική αναζήτηση στα αποσπάσματα. "
        "   - Αν η ερώτηση αναφέρεται σε συγκεκριμένο όρο, αριθμό, ή ημερομηνία, "
        "   αναζήτησε τόσο την ακριβή φράση όσο και συναφείς παραλλαγές. "
        "   - Αν η ερώτηση είναι γενική, αναζήτησε για σχετικές έννοιες και συναφή περιεχόμενο. "
        "4. Αν βρεις ΟΠΟΙΑΔΗΠΟΤΕ σχετική πληροφορία στα αποσπάσματα, απάντησε με βάση αυτή. "
        "5. ΜΟΝΟ αν ΠΡΑΓΜΑΤΙΚΑ δεν υπάρχει ΚΑΜΙΑ σχετική πληροφορία, πες "
        "«Δεν βρέθηκε σχετικό απόσπασμα στο παρεχόμενο.» "
        "\n"
        "Να απαντάς στα ελληνικά."
        )

    # Προσθήκη ειδικών οδηγιών αναζήτησης (hints) βάσει λέξεων-κλειδιών στην ερώτηση.
    question_lower = question.strip().lower()
    search_hint = ""
    
    import re
    
    # Έλεγχος για αναφορές σε "άρθρα" ή νομοθεσία.
    if "άρθρο" in question_lower or "article" in question_lower:
        article_match = re.search(r'άρθρο\s+(\d+)|article\s+(\d+)', question_lower)
        if article_match:
            article_num = article_match.group(1) or article_match.group(2)
            search_hint = f"\n\nΟΔΗΓΙΕΣ ΑΝΑΖΗΤΗΣΗΣ: Αναζήτησε για 'Άρθρο {article_num}' ή 'άρθρο {article_num}' στα αποσπάσματα."
        elif "κύρια" in question_lower or "κύριο" in question_lower:
            search_hint = "\n\nΟΔΗΓΙΕΣ ΑΝΑΖΗΤΗΣΗΣ: Αναζήτησε για νόμους, κώδικες, διατάξεις, ή αναφορές σε φορολογική νομοθεσία στα αποσπάσματα."
    
    # Έλεγχος για χρονικές περιόδους (έτη, τρίμηνα).
    year_match = re.search(r'20\d{2}', question_lower)
    quarter_match = re.search(r'[αβγδ]\'?\s*τρίμηνο|τρίμηνο\s*[1-4]|q[1-4]', question_lower)
    
    if year_match and quarter_match:
        year = year_match.group(0)
        search_hint += f"\n\nΟΔΗΓΙΕΣ ΑΝΑΖΗΤΗΣΗΣ: Η ερώτηση αναφέρεται σε συγκεκριμένη χρονική περίοδο ({year}, τρίμηνο). "
        search_hint += f"Αναζήτησε για: '{year}', 'τρίμηνο', 'Q1/Q2/Q3/Q4', 'α/β/γ/δ τρίμηνο', '1ο/2ο/3ο/4ο τρίμηνο', "
        search_hint += "πίνακες με στατιστικά, αριθμούς, ποσοστά ανάπτυξης, ρυθμούς, ή οποιαδήποτε αριθμητικά δεδομένα. "
        search_hint += "ΠΡΟΣΟΧΗ: Μην αγνοήσεις σχετικές πληροφορίες επειδή δεν περιέχουν την ακριβή φράση - ψάξε για το ΝΟΗΜΑ."
    elif year_match:
        year = year_match.group(0)
        search_hint += f"\n\nΟΔΗΓΙΕΣ ΑΝΑΖΗΤΗΣΗΣ: Η ερώτηση αναφέρεται στο έτος {year}. Αναζήτησε για αυτό το έτος και σχετικά στατιστικά."
    
    # Έλεγχος για αριθμητικά και στατιστικά δεδομένα.
    if any(term in question_lower for term in ['ρυθμός', 'ποσοστό', 'αύξηση', 'μείωση', 'ανάπτυξη', 'πτώση', '%']):
        if not search_hint:
            search_hint = "\n\nΟΔΗΓΙΕΣ ΑΝΑΖΗΤΗΣΗΣ: "
        search_hint += "Η ερώτηση αναφέρεται σε αριθμητικά δεδομένα. Ψάξε για πίνακες, στατιστικά, ποσοστά, και αριθμούς στα αποσπάσματα."
    
    user = f"{question.strip()}{search_hint}\n\nΑποσπάσματα:\n{context_block or '(κανένα διαθέσιμο)'}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]