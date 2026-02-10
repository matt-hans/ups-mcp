import time
import threading

import requests

class OAuthManager:
    def __init__(self, token_url: str, client_id: str | None, client_secret: str | None, timeout: float = 30.0):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.access_token: str | None = None
        self.token_expiry: float = 0
        self._lock = threading.Lock()

    def get_access_token(self) -> str:
        if self._token_is_fresh():
            return self.access_token  # type: ignore[return-value]

        with self._lock:
            if self._token_is_fresh():
                return self.access_token  # type: ignore[return-value]
            if not self.client_id or not self.client_secret:
                raise ValueError("CLIENT_ID and CLIENT_SECRET must be set in environment variables.")

            data = {"grant_type": "client_credentials"}

            response = requests.post(
                self.token_url,
                data=data,
                auth=(self.client_id, self.client_secret),
                timeout=self.timeout,
            )
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data["access_token"]
            self.token_expiry = time.time() + int(token_data.get("expires_in", 0))
            return self.access_token

    def _token_is_fresh(self) -> bool:
        return bool(self.access_token and time.time() < self.token_expiry - 60)
