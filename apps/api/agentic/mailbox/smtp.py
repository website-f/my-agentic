"""My Agentic: sending from an IMAP account over SMTP (stdlib smtplib, run in a thread).

Only encrypted connections, like IMAP: implicit TLS ("ssl", port 465) or STARTTLS
("starttls", port 587). The host is checked like any outside address (core/ssrf.guard_url)
and the connection goes to the checked address with the certificate checked against the
host name. The same user name and app password as the account's IMAP sign-in.
"""

import asyncio
import smtplib
import socket
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any

from ..core.ssrf import BlockedURL, guard_url
from ..i18n import Msg
from .imap import ImapError

TIMEOUT = 30.0
PORTS = frozenset({465, 587, 2525})
PRESETS: dict[str, dict[str, Any]] = {
    "gmail": {"host": "smtp.gmail.com", "port": 465, "security": "ssl"},
    "yahoo": {"host": "smtp.mail.yahoo.com", "port": 465, "security": "ssl"},
    "outlook": {"host": "smtp.office365.com", "port": 587, "security": "starttls"},
    "cpanel": {"host": "", "port": 465, "security": "ssl"},
    "other": {"host": "", "port": 465, "security": "ssl"},
}


class _SSL(smtplib.SMTP_SSL):
    def __init__(self, host: str, ip: str | None, port: int, **kw: Any) -> None:
        self._pin = ip
        super().__init__(host, port, **kw)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:  # type: ignore[override]
        sock = socket.create_connection((self._pin or host, port), timeout)
        return self.context.wrap_socket(sock, server_hostname=host)


class _Plain(smtplib.SMTP):
    def __init__(self, host: str, ip: str | None, port: int, **kw: Any) -> None:
        self._pin = ip
        super().__init__(host, port, **kw)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:  # type: ignore[override]
        return socket.create_connection((self._pin or host, port), timeout)


def _send(
    host: str, ip: str | None, port: int, security: str, user: str, pw: str, msg: EmailMessage
) -> None:
    ctx = ssl.create_default_context()
    try:
        if security == "ssl":
            conn: smtplib.SMTP = _SSL(host, ip, port, context=ctx, timeout=TIMEOUT)
        else:
            conn = _Plain(host, ip, port, timeout=TIMEOUT)
            conn.starttls(context=ctx)
    except (OSError, smtplib.SMTPException) as e:
        raise ImapError(
            Msg("Could not reach {host} on port {port} to send.", host=host, port=port)
        ) from e
    try:
        conn.login(user, pw)
        conn.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise ImapError(
            Msg("The mail server refused the sign-in for sending. Check the app password.")
        ) from e
    except smtplib.SMTPException as e:
        raise ImapError(
            Msg("The mail server did not take the message: {why}", why=str(e)[:200])
        ) from e
    finally:
        try:
            conn.quit()
        except Exception:  # noqa: BLE001,S110 - closing is best effort
            pass


async def real_send(
    host: str, port: int, security: str, user: str, pw: str, msg: EmailMessage
) -> None:
    if port not in PORTS:
        raise ImapError(Msg("Use an SMTP port: 465 (SSL) or 587 (STARTTLS)."))
    try:
        ip = await guard_url(f"https://{host}:{port}/")
    except BlockedURL as e:
        raise ImapError(e.args[0] if e.args else Msg("That server is not allowed.")) from e
    await asyncio.to_thread(_send, host, ip, port, security, user, pw, msg)


# Tests swap this for a fake.
send: Callable[..., Any] = real_send
