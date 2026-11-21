"""A fake SMTP server on 127.0.0.1 for tests, so no test ever sends a real email.

Standard library only. It speaks enough ESMTP for smtplib, keeps what it accepted in memory and
can be scripted, per command, to refuse, drop the connection or hang: `script("RCPT", "550 ...")`
answers the next RCPT with that line. Special answers: DROP closes without replying, HANG stays
silent, TAKE_AND_DROP (for DATA_END) keeps the message and closes without replying, which is a
connection lost after the server took the message.

STARTTLS is offered only when a real TLS context is given (see `localhost_tls`). Passing
`accounts` offers AUTH PLAIN.
"""

import base64
import shutil
import socketserver
import ssl
import subprocess
import threading
from collections import defaultdict
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path
from types import TracebackType
from typing import cast

import pytest

DROP = "DROP"
HANG = "HANG"
TAKE_AND_DROP = "TAKE_AND_DROP"
HANG_SECONDS = 5


@dataclass
class ReceivedMail:
    sender: str
    recipients: list[str]
    data: bytes
    over_tls: bool

    @property
    def email(self) -> EmailMessage:
        return cast(EmailMessage, message_from_bytes(self.data, policy=policy.default))


class _Handler(socketserver.StreamRequestHandler):
    server: "_Server"

    def _write(self, line: str) -> None:
        self.wfile.write(f"{line}\r\n".encode())
        self.wfile.flush()

    def _ehlo(self, tls: bool) -> None:
        fake = self.server.fake
        lines = ["fake.smtp.test", "8BITMIME"]
        if fake.tls_context is not None and not tls:
            lines.append("STARTTLS")
        if fake.accounts:
            lines.append("AUTH PLAIN")
        for line in lines[:-1]:
            self._write(f"250-{line}")
        self._write(f"250 {lines[-1]}")

    def _start_tls(self) -> bool:
        context = self.server.fake.tls_context
        assert context is not None
        self._write("220 Ready to start TLS")
        try:
            self.request = context.wrap_socket(self.request, server_side=True)
        except OSError:
            return False  # the client refused the certificate
        self.connection = self.request
        self.rfile = self.connection.makefile("rb")
        self.wfile = self.connection.makefile("wb")
        return True

    def _auth(self, argument: str) -> str:
        fake = self.server.fake
        _, _, plain = argument.partition(" ")
        _, username, password = base64.b64decode(plain).decode().split("\0")
        fake.logins.append((username, password))
        if fake.accounts.get(username) == password:
            return "235 Accepted"
        return "535 5.7.8 Username and Password not accepted secret-server-text"

    def _read_data(self) -> bytes:
        lines: list[bytes] = []
        while (line := self.rfile.readline()) not in (b".\r\n", b""):
            lines.append(line[1:] if line.startswith(b"..") else line)
        return b"".join(lines)

    def handle(self) -> None:
        fake = self.server.fake
        tls = False
        sender = ""
        recipients: list[str] = []
        self._write("220 fake.smtp.test ESMTP")
        while line := self.rfile.readline():
            text = line.decode().rstrip("\r\n")
            verb, _, argument = text.partition(" ")
            verb = verb.upper()
            fake.commands.append(verb)
            scripted = fake.next_answer(verb)
            if scripted == DROP:
                return
            if scripted == HANG:
                fake.stopping.wait(HANG_SECONDS)
                return
            if verb in ("EHLO", "HELO") and scripted is None:
                self._ehlo(tls)
            elif scripted is not None and verb != "DATA":
                self._write(scripted)
            elif verb == "STARTTLS":
                if not self._start_tls():
                    return
                tls = True
            elif verb == "AUTH":
                self._write(self._auth(argument))
            elif verb == "MAIL":
                sender = argument.split("<", 1)[1].split(">", 1)[0]
                recipients = []
                self._write("250 OK")
            elif verb == "RCPT":
                recipients.append(argument.split("<", 1)[1].split(">", 1)[0])
                self._write("250 OK")
            elif verb == "DATA":
                if scripted is not None:
                    self._write(scripted)
                    continue
                self._write("354 Go ahead")
                data = self._read_data()
                fake.commands.append("DATA_END")
                answer = fake.next_answer("DATA_END")
                if answer in (DROP, HANG):
                    return
                if answer == TAKE_AND_DROP:
                    fake.messages.append(ReceivedMail(sender, recipients, data, tls))
                    return
                if answer is not None:
                    self._write(answer)
                    continue
                fake.messages.append(ReceivedMail(sender, recipients, data, tls))
                self._write("250 OK queued")
            elif verb == "QUIT":
                self._write("221 Bye")
                return
            else:
                self._write("250 OK")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    fake: "FakeSmtp"

    def handle_error(self, request, client_address) -> None:
        pass  # a client that disconnects mid-conversation is what these tests are about


class FakeSmtp:
    def __init__(
        self,
        tls_context: ssl.SSLContext | None = None,
        accounts: dict[str, str] | None = None,
    ) -> None:
        self.tls_context = tls_context
        self.accounts = accounts or {}
        self.commands: list[str] = []
        self.messages: list[ReceivedMail] = []
        self.logins: list[tuple[str, str]] = []
        self.stopping = threading.Event()
        self._answers: defaultdict[str, list[str]] = defaultdict(list)
        self._lock = threading.Lock()
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.fake = self
        self.port: int = self._server.server_address[1]

    def script(self, verb: str, *answers: str) -> None:
        with self._lock:
            self._answers[verb.upper()].extend(answers)

    def next_answer(self, verb: str) -> str | None:
        with self._lock:
            return self._answers[verb].pop(0) if self._answers[verb] else None

    def __enter__(self) -> "FakeSmtp":
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stopping.set()
        self._server.shutdown()
        self._server.server_close()


def localhost_tls(folder: Path) -> tuple[ssl.SSLContext, Path]:
    """A throwaway self-signed certificate for 127.0.0.1: the server's TLS context and the
    certificate file a client must trust. Generated per test, so no key is kept in the
    repository."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is not available to generate a test certificate")
    certificate, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "2",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ],
        check=True,
        capture_output=True,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    return context, certificate
