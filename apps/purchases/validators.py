import os

from django.core.exceptions import ValidationError

MAX_BILL_SIZE = 10 * 1024 * 1024  # 10 MB

# Accepted file types, checked by the file's first bytes ("magic number"),
# not just its extension, so a renamed .exe can't be uploaded as a bill.
_SIGNATURES = {
    ".pdf": [b"%PDF-"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".webp": [b"RIFF"],  # plus "WEBP" at bytes 8-12, checked below
}
ALLOWED_EXTENSIONS = tuple(_SIGNATURES)


def validate_bill_file(f):
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in _SIGNATURES:
        raise ValidationError("Upload a PDF, JPG, PNG or WEBP file.")
    if f.size > MAX_BILL_SIZE:
        raise ValidationError("The file is larger than 10 MB.")

    pos = f.tell() if hasattr(f, "tell") else 0
    f.seek(0)
    head = f.read(16)
    f.seek(pos)

    ok = any(head.startswith(sig) for sig in _SIGNATURES[ext])
    if ext == ".webp":
        ok = ok and head[8:12] == b"WEBP"
    if not ok:
        raise ValidationError("This file's contents don't match its type. Upload a real PDF or image.")
