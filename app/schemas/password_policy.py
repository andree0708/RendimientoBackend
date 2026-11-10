"""Shared password policy."""


def validate_strong_password(value: str) -> str:
    """Require at least 8 chars with one letter and one digit."""
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters long")
    has_letter = any(c.isalpha() for c in value)
    has_digit = any(c.isdigit() for c in value)
    if not (has_letter and has_digit):
        raise ValueError("Password must contain at least one letter and one digit")
    return value
