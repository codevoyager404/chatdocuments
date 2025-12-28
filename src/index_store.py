import json
import os
from dataclasses import dataclass, asdict
from typing import List, Tuple

import faiss
import numpy as np


@dataclass
class Chunk:
    # Δομή δεδομένων που αντιπροσωπεύει ένα τμήμα κειμένου με τα μεταδεδομένα του.
    source: str
    page: int
    text: str
    session_id: str = "default"
    tokens: int = 0  # Αποθηκευμένο πλήθος tokens για βελτιστοποίηση απόδοσης.


class FaissStore:
    # Διαχειρίζεται το ευρετήριο FAISS για αποθήκευση διανυσμάτων και μεταδεδομένων.
    def __init__(self, dim: int, index_path: str, meta_path: str):
        self.dim = dim
        self.index_path = index_path
        self.meta_path = meta_path
        # Χρησιμοποιεί εσωτερικό γινόμενο (Inner Product) για υπολογισμό ομοιότητας.
        # Σε κανονικοποιημένα διανύσματα, αυτό ισοδυναμεί με Cosine Similarity.
        self.index = faiss.IndexFlatIP(dim)
        self.metadata: List[Chunk] = []

    def add(self, vectors: np.ndarray, chunks: List[Chunk]) -> None:
        # Προσθέτει νέα διανύσματα και τα αντίστοιχα τμήματα κειμένου στο ευρετήριο.
        assert vectors.shape[1] == self.dim
        self.index.add(vectors)
        self.metadata.extend(chunks)

    def save(self) -> None:
        # Αποθηκεύει το ευρετήριο FAISS και τα μεταδεδομένα στον δίσκο.
        faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in self.metadata], f, ensure_ascii=False)

    def load(self) -> None:
        # Φορτώνει το ευρετήριο και τα μεταδεδομένα από τον δίσκο, εφόσον υπάρχουν.
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
            try:
                # Ενημερώνει τη διάσταση βάσει του φορτωμένου ευρετηρίου.
                self.dim = self.index.d  # type: ignore[attr-defined]
            except Exception:
                pass
        if os.path.exists(self.meta_path):
            with open(self.meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.metadata = [Chunk(**d) for d in data]

    def search(self, query_vec: np.ndarray, k: int = 5) -> List[Tuple[float, Chunk]]:
        # Εκτελεί αναζήτηση ομοιότητας για να βρει τα k πιο σχετικά τμήματα κειμένου.
        
        # Διασφαλίζει ότι το διάνυσμα αναζήτησης έχει τη σωστή μορφή (2D array).
        if query_vec.ndim == 1:
            query_vec = query_vec[None, :]

        # Αν το ευρετήριο είναι άδειο, επιστρέφει κενή λίστα.
        if self.index.ntotal == 0:
            return []

        # Ανακτά τα scores ομοιότητας και τους δείκτες των αποτελεσμάτων.
        scores, idxs = self.index.search(query_vec, k)
        results: List[Tuple[float, Chunk]] = []

        # Αντιστοιχίζει τους δείκτες του FAISS με τα πραγματικά αντικείμενα Chunk.
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0 or idx >= len(self.metadata):
                continue
            chunk = self.metadata[idx]
            results.append((float(score), chunk))

        return results