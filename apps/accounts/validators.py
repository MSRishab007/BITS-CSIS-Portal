from django.conf import settings
from django.core.exceptions import ValidationError


def validate_allowed_email_domain(value: str) -> None:
    """Only addresses on ALLOWED_EMAIL_DOMAINS may hold accounts.

    Checked against the address itself (exact domain match), so
    'x@pilani.bits-pilani.ac.in' passes but 'x@evil-pilani.bits-pilani.ac.in.com'
    and 'x@goa.bits-pilani.ac.in' do not.
    """
    allowed = getattr(settings, "ALLOWED_EMAIL_DOMAINS", [])
    if not allowed:
        return
    domain = value.rsplit("@", 1)[-1].strip().lower()
    if domain not in allowed:
        raise ValidationError(
            "Only email addresses on %(domains)s are allowed.",
            code="email_domain_not_allowed",
            params={"domains": ", ".join(allowed)},
        )
