import hashlib
import hmac


def verify_github_signature(raw_body: bytes, signature: str | None, secret: str | None) -> bool:
    if not secret:
        return False
    if not signature:
        return False

    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)

