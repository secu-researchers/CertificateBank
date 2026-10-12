"""API 키의 서버 메모리 보관소. 디스크에 쓰지 않고, 브라우저 쿠키에는 무작위 토큰만 둔다."""
import secrets
import threading


class KeyVault:
    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self._lock = threading.Lock()

    def put(self, api_key: str, old_token: str | None = None) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            if old_token:
                self._keys.pop(old_token, None)
            self._keys[token] = api_key
        return token

    def get(self, token: str | None) -> str | None:
        if not token:
            return None
        with self._lock:
            return self._keys.get(token)

    def drop(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._keys.pop(token, None)

    def __repr__(self) -> str:  # 키가 로그나 디버그 출력에 새지 않게 한다
        return f"<KeyVault entries={len(self._keys)}>"
