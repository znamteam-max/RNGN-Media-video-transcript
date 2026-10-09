import threading
import unittest

from runtime_v037 import OperationCancelled, _looks_like_auth_error, _raise_if_cancelled


class V037RuntimeTests(unittest.TestCase):
    def test_youtube_bot_gate_is_auth_error(self) -> None:
        self.assertTrue(_looks_like_auth_error("Sign in to confirm you're not a bot"))
        self.assertTrue(_looks_like_auth_error("Use --cookies-from-browser for the authentication"))

    def test_normal_network_error_is_not_auth_error(self) -> None:
        self.assertFalse(_looks_like_auth_error("connection timed out"))

    def test_cancel_event_stops_operation(self) -> None:
        event = threading.Event()
        event.set()
        with self.assertRaises(OperationCancelled):
            _raise_if_cancelled(event)


if __name__ == "__main__":
    unittest.main()
