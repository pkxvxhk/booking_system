import sys
import threading

from django.core.mail.backends.base import BaseEmailBackend


class ReadableConsoleEmailBackend(BaseEmailBackend):
    def __init__(self, *args, stream=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stream = stream or sys.stdout
        self._lock = threading.RLock()

    def write_message(self, message):
        separator = "-" * 79
        lines = [
            separator,
            f"From: {message.from_email}",
            f"To: {', '.join(message.to)}",
            f"Subject: {message.subject}",
            "",
            message.body,
            separator,
            "",
        ]
        self.stream.write("\n".join(lines))

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        sent = 0
        with self._lock:
            for message in email_messages:
                self.write_message(message)
                sent += 1
            self.stream.flush()
        return sent
