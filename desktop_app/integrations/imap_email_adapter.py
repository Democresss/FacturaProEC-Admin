"""ImapEmailAdapter — standalone (sin dependencias de FacProV2).

Copia literal y autocontenida de
`FacProV2/infrastructure/adapters/imap_email_adapter.py`, eliminando la
herencia de `IEmailImapAdapter` (que vivía en domain/ports de FacProV2)
para que el .exe sea self-contained. Sólo usa `imaplib` + `email` stdlib.

Provee: connect(server, port, user, password) → bool,
        fetch_unread(limit=50) → List[dict] con attachments,
        logout().

El campo carpeta es configurable: 'inbox' por defecto (igual que el
original). El .exe lo irá luego a la pestaña SRI donde el usuario mete
sus creds IMAP de Gmail u otro correo receptor de comprobantes.
"""
from __future__ import annotations

import imaplib
import email
import logging
from email.header import decode_header
from typing import List

logger = logging.getLogger(__name__)


class ImapEmailAdapter:
    """Adapter IMAP para Gmail, Outlook, etc. — 100% stdlib."""

    def __init__(self):
        self.mail = None

    def fetch_invoices(self, config: dict, *, folder: str = "inbox", limit: int = 30) -> List[dict]:
        """Conecta y obtiene correos no leídos con adjuntos."""
        server = config.get("server") or "imap.gmail.com"
        port = config.get("port") or 993
        if port in (587, 465, "587", "465"):
            port = 993
        username = config.get("username") or ""
        password = config.get("password") or ""

        if not username or not password:
            return []

        if self.connect(str(server), int(port), username, password, folder=folder):
            try:
                return self.fetch_unread(limit=limit)
            finally:
                self.logout()
        return []

    def connect(self, server: str, port: int, username: str, password: str,
                *, folder: str = "inbox") -> bool:
        try:
            self.mail = imaplib.IMAP4_SSL(server, port)
            self.mail.login(username, password)
            self.mail.select(folder)
            return True
        except Exception as e:
            logger.error(f"IMAP connect error: {e}")
            return False

    def _decode_str(self, s) -> str:
        if not s:
            return ""
        try:
            parts = decode_header(s)
            result = ""
            for part, enc in parts:
                if isinstance(part, bytes):
                    result += part.decode(enc or "utf-8", errors="replace")
                else:
                    result += part
            return result
        except Exception:
            return str(s)

    def fetch_unread(self, limit: int = 50) -> List[dict]:
        if not self.mail:
            return []

        results = []
        try:
            status, messages = self.mail.search(None, "UNSEEN")
            if status != "OK":
                return []

            for msg_id in messages[0].split()[:limit]:
                try:
                    status, msg_data = self.mail.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    attachments = []
                    for part in msg.walk():
                        filename = part.get_filename() or ""
                        content_type = part.get_content_type()
                        if filename or "xml" in content_type or "pdf" in content_type:
                            content = part.get_payload(decode=True)
                            if content:
                                attachments.append({
                                    "filename": self._decode_str(filename),
                                    "content_bytes": content,
                                    "content_type": content_type
                                })

                    results.append({
                        "from": self._decode_str(msg.get("From", "")),
                        "subject": self._decode_str(msg.get("Subject", "")),
                        "received_at": msg.get("Date", ""),
                        "attachments": attachments
                    })
                except Exception as e:
                    logger.error(f"Error procesando email {msg_id}: {e}")
                    continue
        except Exception as e:
            logger.error(f"fetch_unread: {e}")

        return results

    def logout(self):
        try:
            if self.mail:
                self.mail.logout()
        except Exception:
            pass
        finally:
            self.mail = None
