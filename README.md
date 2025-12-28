Εκτέλεση με Docker

1. Προετοιμασία

Βεβαιωθείτε ότι έχετε εγκατεστημένα:

docker --> https://www.docker.com/get-started/ (το Docker Compose περιλαμβάνεται στο Docker Desktop)
Docker Compose --> https://docs.docker.com/compose/

macOS / Linux
cd /path/to/project
cp env.example .env

Windows
cd C:\path\to\project
copy env.example .env

Ανοίξτε το .env και προσθέστε τα στοιχεία σας από Cloudflare:
CLOUDFLARE_API_TOKEN=το δικό σας token.
CLOUDFLARE_ACCOUNT_ID=το δικό σας account id.

2. Εκκίνηση εφαρμογής

docker-compose up --build

Ανοίξτε τον browser και επισκεφθείτε:
http://localhost:8000
