#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FacPro Tunnel Agent (FacProMux v1) — Agente privado punto a punto para la PC de oficina.

Características:
  - 100% Python stdlib (CERO dependencias externas: funciona en cualquier Python 3.9+ / Windows / Linux / Docker).
  - Cliente WebSocket RFC 6455 binario completo sobre TLS 1.2/1.3 (verifica certificado real del servidor).
  - Autenticación HMAC-SHA256 con timestamp (anti-replay) en headers HTTPS.
  - Allowlist estricta de destinos locales: solo permite abrir TCP hacia `postgres` y `minio`
    configurados localmente (nunca permite escanear puertos arbitrarios).
  - Cero puertos entrantes abiertos en la oficina (solo conexión saliente WSS puerto 443).
  - Reconexión automática con backoff exponencial (0.5s -> 5s) + keepalive PING/PONG.

Uso directo:
  python facpro_tunnel_agent.py \\
      --url wss://facturadorproecuador.org/v2/tunel-byod/ws \\
      --token "<FACPRO_TUNNEL_SECRET>" \\
      --pg 127.0.0.1:5432 \\
      --minio 127.0.0.1:9000
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import logging
import os
import platform
import secrets
import signal
import ssl
import struct
import sys
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit

AGENT_VERSION = "1.0.0"

MSG_OPEN = 0x01
MSG_OPEN_OK = 0x02
MSG_DATA = 0x03
MSG_CLOSE = 0x04
MSG_PING = 0x05
MSG_PONG = 0x06
MSG_EOF = 0x07

HEADER_FMT = "!BII"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
CHUNK_SIZE = 65536
MAX_FRAME_PAYLOAD = 262144

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

logger = logging.getLogger("facpro.tunnel.agent")


def pack_frame(msg_type: int, stream_id: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_FRAME_PAYLOAD:
        raise ValueError(f"Payload demasiado grande: {len(payload)}")
    return struct.pack(HEADER_FMT, msg_type, stream_id & 0xFFFFFFFF, len(payload)) + payload


def unpack_frame(raw: bytes) -> Tuple[int, int, bytes]:
    if not raw or len(raw) < HEADER_SIZE:
        raise ValueError("Frame FacProMux truncado")
    msg_type, stream_id, length = struct.unpack(HEADER_FMT, raw[:HEADER_SIZE])
    if length > MAX_FRAME_PAYLOAD or len(raw) < HEADER_SIZE + length:
        raise ValueError(f"Frame FacProMux inválido (length={length})")
    return msg_type, stream_id, raw[HEADER_SIZE:HEADER_SIZE + length]


def sign_handshake(secret: str, tunnel_id: str, ts: Optional[int] = None) -> Tuple[str, str]:
    ts_str = str(int(ts if ts is not None else time.time()))
    sig = hmac.new(secret.encode("utf-8"), f"{tunnel_id}:{ts_str}".encode("utf-8"), hashlib.sha256).hexdigest()
    return ts_str, sig


def _mask_bytes(data: bytes, mask_key: bytes) -> bytes:
    if not data:
        return b""
    m0, m1, m2, m3 = mask_key[0], mask_key[1], mask_key[2], mask_key[3]
    key_full = (mask_key * ((len(data) // 4) + 1))[:len(data)]
    # XOR rápido usando enteros grandes en C (mucho más veloz que bucle Python byte a byte)
    n = len(data)
    return (int.from_bytes(data, "big") ^ int.from_bytes(key_full, "big")).to_bytes(n, "big")


class StdlibWebSocketClient:
    """Cliente WebSocket RFC 6455 minimalista y rápido sobre asyncio (0 dependencias externas)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._send_lock = asyncio.Lock()
        self.closed = False

    @classmethod
    async def connect(
        cls,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        connect_timeout: float = 15.0,
    ) -> "StdlibWebSocketClient":
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("ws", "wss"):
            raise ValueError(f"Esquema no soportado: {scheme}")
        host = parsed.hostname or ""
        port = parsed.port or (443 if scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        ssl_arg = None
        if scheme == "wss":
            ssl_arg = ssl_context if ssl_context is not None else ssl.create_default_context()

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_arg, server_hostname=host if scheme == "wss" else None),
            timeout=connect_timeout,
        )

        ws_key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        host_header = f"{host}:{port}" if (parsed.port and parsed.port not in (80, 443)) else host
        req_lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host_header}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {ws_key}",
            "Sec-WebSocket-Version: 13",
        ]
        for k, v in (headers or {}).items():
            req_lines.append(f"{k}: {v}")
        req_raw = ("\r\n".join(req_lines) + "\r\n\r\n").encode("utf-8")
        writer.write(req_raw)
        await writer.drain()

        status_line = await asyncio.wait_for(reader.readline(), timeout=connect_timeout)
        if not status_line or b" 101 " not in status_line:
            writer.close()
            raise ConnectionError(f"Handshake WebSocket rechazado: {status_line.decode('utf-8', 'replace').strip()}")

        resp_headers: Dict[str, str] = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=connect_timeout)
            if not line or line in (b"\r\n", b"\n"):
                break
            if b":" in line:
                hk, hv = line.decode("utf-8", "replace").split(":", 1)
                resp_headers[hk.strip().lower()] = hv.strip()

        expected_accept = base64.b64encode(hashlib.sha1((ws_key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        if resp_headers.get("sec-websocket-accept") != expected_accept:
            writer.close()
            raise ConnectionError("Sec-WebSocket-Accept inválido en respuesta del servidor")

        return cls(reader, writer)

    async def _send_raw_frame(self, opcode: int, payload: bytes) -> None:
        if self.closed:
            raise ConnectionError("WebSocket cerrado")
        length = len(payload)
        mask_key = secrets.token_bytes(4)
        header = bytearray([0x80 | (opcode & 0x0F)])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask_key)
        masked = _mask_bytes(payload, mask_key)
        async with self._send_lock:
            self._writer.write(bytes(header) + masked)
            await self._writer.drain()

    async def send_bytes(self, data: bytes) -> None:
        await self._send_raw_frame(0x02, data)

    async def recv_bytes(self) -> bytes:
        """Lee el siguiente mensaje binario completo (respondiendo ping/pong/close RFC 6455 automáticamente)."""
        fragments = bytearray()
        while True:
            hdr = await self._reader.readexactly(2)
            b1, b2 = hdr[0], hdr[1]
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", await self._reader.readexactly(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", await self._reader.readexactly(8))[0]
            if length > MAX_FRAME_PAYLOAD + 64:
                await self.close()
                raise ConnectionError(f"Frame WebSocket excede límite ({length})")
            mask_key = await self._reader.readexactly(4) if masked else b""
            payload = await self._reader.readexactly(length) if length else b""
            if masked:
                payload = _mask_bytes(payload, mask_key)

            if opcode == 0x08:  # CLOSE
                self.closed = True
                raise EOFError("Servidor cerró el WebSocket")
            if opcode == 0x09:  # PING -> responder PONG
                await self._send_raw_frame(0x0A, payload)
                continue
            if opcode == 0x0A:  # PONG
                continue
            if opcode in (0x01, 0x02, 0x00):
                fragments.extend(payload)
                if fin:
                    return bytes(fragments)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self._send_raw_frame(0x08, b"")
        except Exception:
            pass
        try:
            self._writer.close()
        except Exception:
            pass


class FacProTunnelAgent:
    """Agente de oficina: conecta por WSS al backend y atiende streams TCP solo a destinos en allowlist."""

    def __init__(
        self,
        ws_url: str,
        secret: str,
        targets: Dict[str, Tuple[str, int]],
        tunnel_id: str = "default",
        ssl_context: Optional[ssl.SSLContext] = None,
    ):
        self.ws_url = ws_url
        self.secret = secret
        self.targets = {k.strip().lower(): (str(h), int(p)) for k, (h, p) in targets.items()}
        self.tunnel_id = tunnel_id or "default"
        self.ssl_context = ssl_context
        self._stop_event = asyncio.Event()
        self._ws: Optional[StdlibWebSocketClient] = None
        self._streams: Dict[int, Tuple[asyncio.StreamReader, asyncio.StreamWriter, asyncio.Task]] = {}

    def stop(self) -> None:
        self._stop_event.set()

    async def _send_mux(self, msg_type: int, stream_id: int, payload: bytes = b"") -> None:
        ws = self._ws
        if ws is None or ws.closed:
            return
        await ws.send_bytes(pack_frame(msg_type, stream_id, payload))

    async def _close_local_stream(self, sid: int, notify_remote: bool = True, reason: str = "") -> None:
        entry = self._streams.pop(sid, None)
        if entry is not None:
            _, writer, task = entry
            try:
                writer.close()
            except Exception:
                pass
            if task is not None and not task.done() and task is not asyncio.current_task():
                task.cancel()
        if notify_remote:
            try:
                await self._send_mux(MSG_CLOSE, sid, reason.encode("utf-8")[:120])
            except Exception:
                pass

    async def _open_local_stream(self, sid: int, target_name: str) -> None:
        key = target_name.strip().lower()
        if key not in self.targets:
            logger.warning("Bloqueado target fuera de allowlist: %r (stream %d)", target_name, sid)
            await self._send_mux(MSG_CLOSE, sid, b"target_not_allowed")
            return
        host, port = self.targets[key]
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5.0)
        except Exception as e:
            logger.debug("No se pudo conectar a %s (%s:%d): %s", key, host, port, e)
            await self._send_mux(MSG_CLOSE, sid, f"connect_failed:{type(e).__name__}".encode("utf-8"))
            return

        async def _pump_local_to_ws():
            try:
                while not self._stop_event.is_set() and self._ws and not self._ws.closed:
                    chunk = await reader.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    await self._send_mux(MSG_DATA, sid, chunk)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            finally:
                await self._close_local_stream(sid, notify_remote=True)

        task = asyncio.create_task(_pump_local_to_ws())
        self._streams[sid] = (reader, writer, task)
        await self._send_mux(MSG_OPEN_OK, sid)

    async def run_once(self) -> None:
        """Ejecuta una sesión conectada hasta desconexión o stop()."""
        ts_str, sig = sign_handshake(self.secret, self.tunnel_id)
        sep = "&" if "?" in self.ws_url else "?"
        url_with_id = f"{self.ws_url}{sep}tunnel_id={self.tunnel_id}" if "tunnel_id=" not in self.ws_url else self.ws_url
        headers = {
            "X-FacPro-Tunnel-Ts": ts_str,
            "X-FacPro-Tunnel-Sig": sig,
            "X-FacPro-Agent-Host": platform.node()[:120],
            "X-FacPro-Agent-Version": AGENT_VERSION,
        }
        ws = await StdlibWebSocketClient.connect(url_with_id, headers=headers, ssl_context=self.ssl_context)
        self._ws = ws
        logger.info("FacPro Tunnel conectado a %s (tunnel_id=%s, targets=%s)", self.ws_url, self.tunnel_id, list(self.targets.keys()))
        try:
            while not self._stop_event.is_set() and not ws.closed:
                recv_task = asyncio.create_task(ws.recv_bytes())
                stop_task = asyncio.create_task(self._stop_event.wait())
                done, pending = await asyncio.wait({recv_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
                for p in pending:
                    p.cancel()
                if stop_task in done:
                    break
                raw = recv_task.result()
                msg_type, sid, payload = unpack_frame(raw)

                if msg_type == MSG_OPEN:
                    target_name = payload.decode("utf-8", "replace")
                    asyncio.create_task(self._open_local_stream(sid, target_name))
                elif msg_type == MSG_DATA:
                    entry = self._streams.get(sid)
                    if entry is not None:
                        _, writer, _ = entry
                        try:
                            writer.write(payload)
                            await writer.drain()
                        except Exception:
                            await self._close_local_stream(sid, notify_remote=True, reason="write_error")
                elif msg_type == MSG_EOF:
                    entry = self._streams.get(sid)
                    if entry is not None:
                        _, writer, _ = entry
                        try:
                            if writer.can_write_eof():
                                writer.write_eof()
                        except Exception:
                            pass
                elif msg_type == MSG_CLOSE:
                    await self._close_local_stream(sid, notify_remote=False)
                elif msg_type == MSG_PING:
                    await self._send_mux(MSG_PONG, 0, payload)
        finally:
            for sid in list(self._streams.keys()):
                await self._close_local_stream(sid, notify_remote=False)
            await ws.close()
            self._ws = None

    async def run_forever(self) -> None:
        """Mantiene el túnel vivo con reconexión automática (backoff 0.5s -> 5s)."""
        backoff = 0.5
        while not self._stop_event.is_set():
            started = time.time()
            try:
                await self.run_once()
            except Exception as e:
                logger.warning("FacPro Tunnel desconectado: %s — reintentando en %.1fs", e, backoff)
            if self._stop_event.is_set():
                break
            if (time.time() - started) > 30.0:
                backoff = 0.5
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(5.0, backoff * 2.0)


def _parse_hostport(raw: str) -> Tuple[str, int]:
    h, p = raw.rsplit(":", 1)
    return h.strip(), int(p.strip())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser(description="FacPro Tunnel Agent — Túnel privado punto a punto (0 puertos públicos)")
    ap.add_argument("--url", default=os.getenv("FACPRO_TUNNEL_URL", "wss://facturadorproecuador.org/v2/tunel-byod/ws"))
    ap.add_argument("--token", default=os.getenv("FACPRO_TUNNEL_SECRET", ""), help="Secreto compartido FACPRO_TUNNEL_SECRET")
    ap.add_argument("--tunnel-id", default=os.getenv("FACPRO_TUNNEL_ID", "default"))
    ap.add_argument("--pg", default=os.getenv("FACPRO_TUNNEL_PG_TARGET", "127.0.0.1:5432"))
    ap.add_argument("--minio", default=os.getenv("FACPRO_TUNNEL_MINIO_TARGET", "127.0.0.1:9000"))
    args = ap.parse_args()

    if not args.token or len(args.token.strip()) < 16:
        logger.error("Debes pasar --token o FACPRO_TUNNEL_SECRET (mínimo 16 caracteres).")
        sys.exit(2)

    targets = {
        "postgres": _parse_hostport(args.pg),
        "minio": _parse_hostport(args.minio),
    }
    agent = FacProTunnelAgent(ws_url=args.url, secret=args.token.strip(), targets=targets, tunnel_id=args.tunnel_id)

    async def _run():
        loop = asyncio.get_running_loop()
        for sig_name in ("SIGINT", "SIGTERM"):
            s = getattr(signal, sig_name, None)
            if s is not None:
                try:
                    loop.add_signal_handler(s, agent.stop)
                except NotImplementedError:
                    pass
        await agent.run_forever()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
