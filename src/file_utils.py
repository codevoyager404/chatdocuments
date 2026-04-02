import os
import re
import uuid

SAFE_NAME_RE = re.compile(r'[^A-Za-z0-9._-]+')


def safe_filename(name: str) -> str:
    base = os.path.basename(name).replace('\\', '/').split('/')[-1]
    base = SAFE_NAME_RE.sub('_', base)
    base = base.strip('._-')[:120]
    return base or f'file_{uuid.uuid4().hex}'

def temp_filename(original_name: str) -> str:
    safe_name = safe_filename(original_name)
    return f"upload_{safe_name}"
