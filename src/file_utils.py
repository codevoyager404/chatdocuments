import os
import re
import uuid

# Regex για αφαίρεση χαρακτήρων που δεν είναι ασφαλείς σε όνομα αρχείου
SAFE_NAME_RE = re.compile(r'[^A-Za-z0-9._-]+')


def safe_filename(name: str) -> str:
    # Παίρνουμε μόνο το basename (χωρίς path)
    base = os.path.basename(name).replace('\\', '/').split('/')[-1]
    # Αντικαθιστούμε περίεργους χαρακτήρες με "_"
    base = SAFE_NAME_RE.sub('_', base)
    # Κόβουμε αρχικά/τελικά σημάδια και περιορίζουμε σε 120 χαρακτήρες
    base = base.strip('._-')[:120]
    # Αν μείνει άδειο, φτιάχνουμε τυχαίο όνομα με uuid
    return base or f'file_{uuid.uuid4().hex}'

def temp_filename(original_name: str) -> str:
    # Προσθέτουμε prefix για προσωρινά uploads
    safe_name = safe_filename(original_name)
    return f"upload_{safe_name}"
