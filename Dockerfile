FROM python:3.11-slim

# Ορισμός φακέλου εργασίας
WORKDIR /app

# Περιβάλλον Python 
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Εγκατάσταση απαραίτητων εργαλείων
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Αντιγραφή requirements και εγκατάσταση πακέτων
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Αντιγραφή υπόλοιπου κώδικα
COPY . .

# Δημιουργία φακέλων για δεδομένα, logs και chat_history
RUN mkdir -p data/index data/uploads data/logs data/chat_history static

# Port για την εφαρμογή
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Εκκίνηση εφαρμογής με uvicorn και hot reload
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]