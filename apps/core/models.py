from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base: every table gets created/updated timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True
