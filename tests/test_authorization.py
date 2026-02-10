import threading
import time
import unittest
from unittest.mock import Mock, patch

from ups_mcp.authorization import OAuthManager


def fake_token_response(token_value: str, expires_in: int = 3600) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"access_token": token_value, "expires_in": expires_in}
    return response


class OAuthManagerTests(unittest.TestCase):
    @patch("ups_mcp.authorization.requests.post")
    def test_reuses_unexpired_token(self, mock_post: Mock) -> None:
        mock_post.return_value = fake_token_response("token-1")
        manager = OAuthManager(
            token_url="https://example.test/token",
            client_id="client-id",
            client_secret="client-secret",
        )

        first = manager.get_access_token()
        second = manager.get_access_token()

        self.assertEqual(first, "token-1")
        self.assertEqual(second, "token-1")
        self.assertEqual(mock_post.call_count, 1)

    @patch("ups_mcp.authorization.requests.post")
    def test_refreshes_expired_token(self, mock_post: Mock) -> None:
        mock_post.side_effect = [
            fake_token_response("token-1", expires_in=1),
            fake_token_response("token-2", expires_in=3600),
        ]
        manager = OAuthManager(
            token_url="https://example.test/token",
            client_id="client-id",
            client_secret="client-secret",
        )

        first = manager.get_access_token()
        time.sleep(1.1)
        second = manager.get_access_token()

        self.assertEqual(first, "token-1")
        self.assertEqual(second, "token-2")
        self.assertEqual(mock_post.call_count, 2)

    @patch("ups_mcp.authorization.requests.post")
    def test_concurrent_calls_refresh_only_once(self, mock_post: Mock) -> None:
        mock_post.return_value = fake_token_response("token-1")
        manager = OAuthManager(
            token_url="https://example.test/token",
            client_id="client-id",
            client_secret="client-secret",
        )

        results: list[str] = []
        start_barrier = threading.Barrier(5)

        def worker() -> None:
            start_barrier.wait()
            results.append(manager.get_access_token())

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 5)
        self.assertTrue(all(item == "token-1" for item in results))
        self.assertEqual(mock_post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
