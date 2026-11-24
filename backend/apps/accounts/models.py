from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Syntropy user.

    Empty for now, but defined from the first migration so fields (phone, preferences,
    the technical toggle from ADR-21) can be added later without a painful swap.
    """
