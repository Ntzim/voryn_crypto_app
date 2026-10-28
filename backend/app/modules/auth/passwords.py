"""Password policy (NIST SP 800-63B): length over composition rules, block obvious choices."""

from app.core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

_COMMON = frozenset(
    {
        "1234567890",
        "12345678910",
        "123456789a",
        "qwertyuiop",
        "password123",
        "password1234",
        "senha12345",
        "senha123456",
        "bitcoin123",
        "bitcoin1234",
        "abcdefghij",
        "0123456789",
        "voryn12345",
        "iloveyou123",
        "1q2w3e4r5t",
        "q1w2e3r4t5",
    }
)


def validate_password_strength(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"A senha deve ter pelo menos {PASSWORD_MIN_LENGTH} caracteres.")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"A senha deve ter no máximo {PASSWORD_MAX_LENGTH} caracteres.")
    if len(set(password)) < 4 or password.lower() in _COMMON:
        raise ValueError("Essa senha é muito previsível. Escolha uma combinação menos comum.")
    return password
