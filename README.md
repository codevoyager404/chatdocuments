# ChatDocuments

Web εφαρμογή για συνομιλία με αρχεία PDF και PowerPoint μέσω FastAPI, vector search και Cloudflare AI.

Το project περιλαμβάνει:

- backend σε `FastAPI`
- frontend σε στατικά αρχεία `HTML/CSS/JavaScript`
- υποστήριξη για αρχεία `.pdf` και `.pptx`
- αποθήκευση session data και chat history τοπικά

## Απαιτήσεις

Πριν την τοπική εγκατάσταση, βεβαιώσου ότι υπάρχουν:

- Python `3.11` ή νεότερο
- `pip`
- πρόσβαση σε Cloudflare AI
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`

Προαιρετικά:

- Docker Desktop, αν προτιμάς εκτέλεση μέσω containers

## Τοπική εγκατάσταση με Python

### 1. Μετάβαση στο project

```bash
cd /path/to/project
```

### 2. Δημιουργία virtual environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Εγκατάσταση dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Ρύθμιση μεταβλητών περιβάλλοντος

Αντέγραψε το αρχείο παραδείγματος:

macOS / Linux:

```bash
cp env.example .env
```

Windows:

```powershell
copy env.example .env
```

Συμπλήρωσε στο `.env`:

```env
CLOUDFLARE_ACCOUNT_ID=your_account_id
CLOUDFLARE_API_TOKEN=your_api_token
```

### 5. Εκκίνηση της εφαρμογής

```bash
uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Άνοιγμα στον browser

Άνοιξε:

[http://localhost:8000](http://localhost:8000)

## Εκτέλεση με Docker

Αν θέλεις τοπική εκτέλεση χωρίς Python virtual environment:

### 1. Δημιούργησε το `.env`

```bash
cp env.example .env
```

Συμπλήρωσε τα:

```env
CLOUDFLARE_ACCOUNT_ID=your_account_id
CLOUDFLARE_API_TOKEN=your_api_token
```

### 2. Εκκίνηση

```bash
docker-compose up --build
```

Η εφαρμογή θα είναι διαθέσιμη στο:

[http://localhost:8000](http://localhost:8000)

## Δομή φακέλων

```text
src/        Backend λογική FastAPI και AI integration
static/     Frontend αρχεία
data/       Τοπικά uploads, index και chat history
```

Ο φάκελος `data/` δημιουργείται κατά την εκτέλεση αν δεν υπάρχει.

## Συχνά προβλήματα

### Λείπουν μεταβλητές περιβάλλοντος

Αν δεις σφάλμα για `CLOUDFLARE_ACCOUNT_ID` ή `CLOUDFLARE_API_TOKEN`, έλεγξε ότι:

- υπάρχει `.env`
- οι τιμές είναι σωστές
- το app ξεκινά από τον root φάκελο του project

### Πρόβλημα στην εγκατάσταση `faiss-cpu`

Σε ορισμένα συστήματα χρειάζονται ενημερωμένα εργαλεία `pip`, `setuptools`, `wheel`:

```bash
pip install --upgrade pip setuptools wheel
```

### Η εφαρμογή ανοίγει αλλά δεν απαντά

Συνήθως αυτό σημαίνει ότι:

- δεν έχουν οριστεί σωστά τα Cloudflare credentials
- υπάρχει αποτυχία πρόσβασης προς το Cloudflare AI API
- το αρχείο που ανέβηκε δεν είναι έγκυρο `.pdf` ή `.pptx`

## Ανάπτυξη

Για development, η βασική εντολή είναι:

```bash
uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
```

Για καθαρό restart, σταμάτα το process και ξανατρέξε την ίδια εντολή.
