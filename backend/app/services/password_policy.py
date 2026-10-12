import re

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def password_policy_errors(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if not re.search(r"[A-Z]", password):
        errors.append("Include at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Include at least one lowercase letter.")
    if not re.search(r"\d", password):
        errors.append("Include at least one number.")
    if not re.search(r"[^A-Za-z0-9\s]", password):
        errors.append("Include at least one special character.")
    return errors


def ensure_password_policy(password: str) -> None:
    errors = password_policy_errors(password)
    if errors:
        raise ValueError("Password requirements: " + " ".join(errors))
