import re
from typing import List, Tuple
from pypdf import PdfReader


def extract_pdf_text_with_pages(path: str) -> List[Tuple[int, str]]:
    # Εξάγει το κείμενο από αρχεία PDF.
    # Επιστρέφει μια λίστα με ζεύγη (αριθμός σελίδας, κείμενο).
    reader = PdfReader(path)
    results: List[Tuple[int, str]] = []
    
    # Διαβάζω το PDF σελίδα προς σελίδα.
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        
        # Αφαιρώ ειδικούς χαρακτήρες (όπως ενωτικά συλλαβισμού και αλλαγές γραμμής)
        # για να δημιουργήσω καθαρότερο κείμενο προς επεξεργασία.
        text = text.replace("\u00ad", "").replace("\r", " ")
        results.append((i, text))
        
    return results


def _split_into_sentences(text: str) -> List[str]:
    # Διαχωρίζει το κείμενο σε επιμέρους προτάσεις.
    # Υποστηρίζει το ελληνικό αλφάβητο και χρησιμοποιεί Regular Expressions.
    
    # Αντικαθιστώ τα πολλαπλά κενά με ένα και αφαιρώ τα κενά στην αρχή/τέλος.
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Εφαρμόζω διαχωρισμό σε τελείες, θαυμαστικά και ερωτηματικά, αποφεύγοντας λανθασμένες διακοπές.
    sentences = re.split(r'(?<=[.!;]) +(?=[Α-ΩA-Z])|(?<=\.) (?=[Α-ΩA-Z])', text)
    
    # Φιλτράρω και αφαιρώ τυχόν κενές συμβολοσειρές από τα αποτελέσματα.
    return [s.strip() for s in sentences if s.strip()]


def chunk_text(
    text: str,
    chunk_size: int = 1200,
    chunk_overlap: int = 200,
    prefix: str = "",
    prefix_max_tokens: int = 8,
    preserve_sentences: bool = True,
) -> List[str]:
    # Τεμαχίζει το κείμενο σε μικρότερα τμήματα (chunks) για σημασιολογική αναζήτηση.
    if not text:
        return []

    # Υπολογίζω το μέγεθος του προθέματος (prefix) για να βρω τον πραγματικό διαθέσιμο χώρο.
    prefix_tokens = (prefix or "").split()[: max(0, prefix_max_tokens)]
    effective_size = max(1, chunk_size - len(prefix_tokens))

    # Εάν έχει επιλεγεί η διατήρηση προτάσεων, διαχωρίζω το κείμενο βάσει συντακτικής δομής.
    if preserve_sentences:
        sentences = _split_into_sentences(text)
        if not sentences:
            # Αν δεν βρεθούν προτάσεις, εφαρμόζω εναλλακτική μέθοδο διαχωρισμού βάσει λέξεων.
            return chunk_text(text, chunk_size, chunk_overlap, prefix, prefix_max_tokens, preserve_sentences=False)
        
        chunks: List[str] = []
        current_chunk: List[str] = []
        current_length = 0
        
        for sentence in sentences:
            sentence_tokens = sentence.split()
            sentence_length = len(sentence_tokens)
            
            # Ελέγχω αν η πρόταση χωράει στο τρέχον τμήμα και την προσθέτω.
            if current_length + sentence_length <= effective_size:
                current_chunk.append(sentence)
                current_length += sentence_length
            else:
                # Ολοκληρώνω το τρέχον τμήμα και το αποθηκεύω στη λίστα.
                if current_chunk:
                    chunk_text_str = " ".join(current_chunk).strip()
                    if chunk_text_str:
                        final_chunk = (" ".join(prefix_tokens + [chunk_text_str])).strip()
                        chunks.append(final_chunk)
                
                # Διαχειρίζομαι προτάσεις που υπερβαίνουν από μόνες τους το μέγιστο μέγεθος,
                # χωρίζοντάς τες αναγκαστικά σε μικρότερα κομμάτια λέξεων.
                if sentence_length > effective_size:
                    words = sentence_tokens
                    for i in range(0, len(words), effective_size):
                        chunk_words = words[i:i + effective_size]
                        chunk_text_str = " ".join(chunk_words).strip()
                        if chunk_text_str:
                            final_chunk = (" ".join(prefix_tokens + [chunk_text_str])).strip()
                            chunks.append(final_chunk)
                    current_chunk = []
                    current_length = 0
                else:
                    # Υπολογίζω την επικάλυψη (overlap) διατηρώντας τις τελευταίες προτάσεις
                    # του προηγούμενου τμήματος για τη διασφάλιση της συνέχειας (context).
                    if chunk_overlap > 0 and len(current_chunk) > 0:
                        overlap_sentences = []
                        overlap_length = 0
                        for sent in reversed(current_chunk):
                            sent_len = len(sent.split())
                            if overlap_length + sent_len <= chunk_overlap:
                                overlap_sentences.insert(0, sent)
                                overlap_length += sent_len
                            else:
                                break
                        current_chunk = overlap_sentences
                        current_length = overlap_length
                    else:
                        current_chunk = []
                        current_length = 0
                    
                    # Ξεκινώ το νέο τμήμα με την τρέχουσα πρόταση.
                    current_chunk.append(sentence)
                    current_length += sentence_length
        
        # Αποθηκεύω το τελευταίο τμήμα κειμένου που απέμεινε.
        if current_chunk:
            chunk_text_str = " ".join(current_chunk).strip()
            if chunk_text_str:
                final_chunk = (" ".join(prefix_tokens + [chunk_text_str])).strip()
                chunks.append(final_chunk)
        
        return chunks
    
    # Εναλλακτική μέθοδος: Διαχωρισμός βάσει πλήθους λέξεων (sliding window).
    tokens = text.split()
    chunks: List[str] = []
    start = 0
    while start < len(tokens):
        end = min(len(tokens), start + effective_size)
        main = " ".join(tokens[start:end]).strip()
        if main:
            chunk = (" ".join(prefix_tokens + [main])).strip()
            chunks.append(chunk)
        if end == len(tokens):
            break
        # Μετακινώ το παράθυρο ανάγνωσης λαμβάνοντας υπόψη την επικάλυψη.
        start = max(0, end - chunk_overlap)

    return chunks