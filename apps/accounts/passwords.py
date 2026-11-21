import secrets

from django.conf import settings

# Characters that are easy to confuse (0/O, 1/l/I, 5/S, 2/Z, 8/B) are left out
# so a password can be read aloud or copied by hand without mistakes.
UPPER = "ACDEFGHJKMNPQRTUVWXY"
LOWER = "abcdefghjkmnpqrtuvwxy"
DIGITS = "34679"
ALPHABET = UPPER + LOWER + DIGITS


def generate_password(length: int | None = None) -> str:
    """Return a random, readable password such as 'Kx7m-Qp4t-Wr9z'.

    Uses the `secrets` module (cryptographically secure). Always contains at
    least one upper-case letter, one lower-case letter and one digit, and is
    grouped in fours with dashes for readability.
    """
    length = length or getattr(settings, "GENERATED_PASSWORD_LENGTH", 12)
    length = max(length, 8)
    while True:
        chars = [secrets.choice(ALPHABET) for _ in range(length)]
        if (any(c in UPPER for c in chars)
                and any(c in LOWER for c in chars)
                and any(c in DIGITS for c in chars)):
            break
    raw = "".join(chars)
    return "-".join(raw[i:i + 4] for i in range(0, length, 4))


def set_generated_password(user) -> str:
    """Give `user` a new generated password and force a change at next sign-in.

    Saves the user and returns the plain password so it can be shown ONCE.
    Only the hash is stored.
    """
    password = generate_password()
    user.set_password(password)
    user.must_change_password = True
    user.save()
    return password
