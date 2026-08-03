import hmac
import hashlib
import time

def sign(secret: str, body: bytes, ts: str) -> str:
    msg = ts.encode() + b"." + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()

def verify(secret: str, body: bytes, ts: str, sig: str, max_skew_s: int = 60) -> bool:
    try:
        t = int(ts)
    except Exception:
        return False
    if abs(int(time.time()) - t) > max_skew_s:
        return False
    expected = sign(secret, body, ts)
    return hmac.compare_digest(expected, sig)
