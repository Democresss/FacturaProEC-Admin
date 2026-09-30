"""sri_facade — pegamento standalone del módulo SRI para la GUI.

Orquesta los 3 adaptadores autocontenidos en `integrations/` más un
repositorio SQL mínimo (SQLAlchemy async, tabla propia `facturapro_inbox`)
para persistir comprobantes recibidos en la BD del usuario (PG local Docker,
PG remoto VPN, o fallback SQLite).

El facade NO depende de FacProV2 (ni Firestore ni FastAPI ni el
SQLInboxRepository hexagonal). Es unровать único entre:
  • `RucConsultor` (catastro REST público, sin auth)
  • `ImapEmailAdapter` (imaplib stdlib)
  • `XmlSriParserAdapter.parse_with_envelope()` (maneja autorizaciones SRI)
  • Repositorio SQL mínimo (crea la tabla si no existe) — un único
    modelo declarativo `InboxComprobanteRow`.

La tabla destino `facturapro_inbox` tiene estos campos:
    id (PK), clave_acceso (UNIQUE), tipo_comprobante, ambiente,
    ruc_emisor, razon_social_emisor, fecha_emision, fecha_autorizacion,
    importe_total, estado_autorizacion, numero_autorizacion,
    emisor_email, asunto_email, recibido_email_at,
    xml_recibido (TEXT), org_id, created_at.

Cuando el usuario conecta a la PG de FacProV2, los datos viven aquí
también; la BD real del SRI viva en `inbox_comprobantes` no se toca
(no duplicamos ese flujo). Quien quiera cuadrar con OC debe ir por la
interfaz web de FacProV2.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Float, Text, DateTime, Integer, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import declarative_base

from integrations.imap_email_adapter import ImapEmailAdapter
from integrations.xml_sri_parser_adapter import XmlSriParserAdapter
from integrations.ruc_consultor import RucConsultor, SRIServiceMaintenanceError
from ui.tabs.db_viewer.connection_manager import DbConfig, get_default as get_connection_manager

logger = logging.getLogger(__name__)

_Base = declarative_base()


class InboxComprobanteRow(_Base):
    """Tabla propia del módulo SRI de la app desktop."""
    __tablename__ = "facturapro_inbox"
    id = Column(Integer, primary_key=True, autoincrement=True)
    clave_acceso = Column(String(49), unique=True, index=True, nullable=False)
    tipo_comprobante = Column(String(4), index=True)
    ambiente = Column(String(32))
    ruc_emisor = Column(String(13), index=True)
    razon_social_emisor = Column(String(256))
    fecha_emision = Column(String(32))
    fecha_autorizacion = Column(String(48))
    importe_total = Column(Float)
    estado_autorizacion = Column(String(32))
    numero_autorizacion = Column(String(49))
    emisor_email = Column(String(256))
    asunto_email = Column(String(512))
    recibido_email_at = Column(String(48))
    xml_recibido = Column(Text)
    org_id = Column(String(64), index=True, default="default")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("clave_acceso", name="uq_facturapro_inbox_clave"),)


@dataclass
class SyncStats:
    emails_processados: int
    comprobantes_encontrados: int
    comprobantes_nuevos: int
    comprobantes_duplicados: int
    errores: int
    detalle: str = ""


class SRIFacade:
    """Fachada standalone del módulo SRI para la GUI desktop.

    Cada método es SÍNCRONO (llamable seguro desde un hilo del
    AsyncActionRunner, ya que crea su propio event loop interno).
    """

    def __init__(self, cfg: DbConfig):
        self.cfg = cfg
        self.cm = get_connection_manager()
        self.engine: AsyncEngine = self.cm.get_async_engine(cfg)

    # ─── Probar IMAP (sin guardar) ─────────────────────────────────
    def test_imap(self, server: str, port: int, user: str, password: str,
                  folder: str = "inbox") -> tuple[bool, str]:
        adapter = ImapEmailAdapter()
        if not user or not password:
            return (False, "Falta usuario o contraseña.")
        ok = adapter.connect(server, int(port or 993), user, password, folder=folder)
        if not ok:
            return (False, f"No se pudo conectar a {server}:{port}. Verifica usuario/contraseña y que app-password esté habilitado (Gmail).")
        try:
            # Hacer una consulta mínima para confirmar que la sesión es válida
            lista = adapter.fetch_unread(limit=1)
            return (True, f"✅ Conectado a {server}:{port} como '{user}'. "
                          f"Correos no leídos disponibles: {len(lista) >= 1 if lista else 0} "
                          f"(inmediatamente visible).")
        except Exception as e:
            return (False, f"Conexión OK pero falló leer el buzón: {e}")
        finally:
            adapter.logout()

    # ─── Sincronizar IMAP y persistir ──────────────────────────────
    def sync_inbox(self, server: str, port: int, user: str, password: str,
                   *, folder: str = "inbox", limit: int = 50,
                   org_id: str = "default",
                   on_progress=None) -> SyncStats:
        adapter = ImapEmailAdapter()
        if not user or not password:
            return SyncStats(0, 0, 0, 0, 1, "Falta usuario o contraseña IMAP.")
        ok = adapter.connect(server, int(port or 993), user, password, folder=folder)
        if not ok:
            return SyncStats(0, 0, 0, 0, 1, f"No se pudo conectar: {server}:{port}")
        try:
            emails = adapter.fetch_unread(limit=limit)
            stats = SyncStats(emails_processados=len(emails), comprobantes_encontrados=0,
                              comprobantes_nuevos=0, comprobantes_duplicados=0, errores=0)
            parser = XmlSriParserAdapter()

            comprobantes = []
            for em in emails:
                for att in em.get("attachments", []):
                    fname = (att.get("filename") or "").lower()
                    ct = (att.get("content_type") or "").lower()
                    if not (fname.endswith(".xml") or "xml" in ct):
                        continue
                    data = att.get("content_bytes") or b""
                    if not data:
                        continue
                    stats.comprobantes_encontrados += 1
                    parsed = parser.parse_with_envelope(data)
                    if not parsed or not parsed.get("claveAcceso"):
                        stats.errores += 1
                        continue
                    comprobantes.append({
                        "clave_acceso": parsed["claveAcceso"],
                        "tipo_comprobante": parsed.get("tipoComprobante"),
                        "ambiente": parsed.get("ambiente"),
                        "ruc_emisor": parsed.get("rucEmisor"),
                        "razon_social_emisor": parsed.get("razonSocialEmisor"),
                        "fecha_emision": parsed.get("fechaEmision"),
                        "fecha_autorizacion": parsed.get("fechaAutorizacion"),
                        "importe_total": float(parsed.get("total") or 0.0),
                        "estado_autorizacion": parsed.get("estadoAutorizacion"),
                        "numero_autorizacion": parsed.get("numeroAutorizacion"),
                        "emisor_email": em.get("from", ""),
                        "asunto_email": em.get("subject", ""),
                        "recibido_email_at": em.get("received_at", ""),
                        "xml_recibido": data.decode("utf-8", errors="replace"),
                        "org_id": org_id,
                    })
                    if on_progress:
                        try:
                            on_progress(parsed["claveAcceso"])
                        except Exception:
                            pass

            # Persistir
            nuevos, duplicados, err = self._persist(comprobantes)
            stats.comprobantes_nuevos = nuevos
            stats.comprobantes_duplicados = duplicados
            stats.errores += err
            return stats
        finally:
            adapter.logout()

    def _persist(self, comprobantes: list[dict]) -> tuple[int, int, int]:
        """Inserta ignorando duplicados por clave_acceso. Devuelve (nuevos, duplicados, errores)."""
        async def _run():
            # Asegurar tabla
            async with self.engine.begin() as conn:
                await conn.run_sync(_Base.metadata.create_all)
            nuevos = 0
            duplicados = 0
            errores = 0
            # `created_at` lo enviamos desde Python (datetime.utcnow) en vez
            # de invocar NOW() en SQL — así es portable entre PG y SQLite.
            from datetime import datetime as _dt
            now = _dt.utcnow()
            for c in comprobantes:
                try:
                    async with self.engine.begin() as conn:
                        from sqlalchemy import text
                        exists = (await conn.execute(
                            text("SELECT 1 FROM facturapro_inbox WHERE clave_acceso = :ca"),
                            {"ca": c["clave_acceso"]}
                        )).scalar()
                        if exists:
                            duplicados += 1
                            continue
                        await conn.execute(text(
                            "INSERT INTO facturapro_inbox "
                            "(clave_acceso, tipo_comprobante, ambiente, ruc_emisor, "
                            " razon_social_emisor, fecha_emision, fecha_autorizacion, "
                            " importe_total, estado_autorizacion, numero_autorizacion, "
                            " emisor_email, asunto_email, recibido_email_at, xml_recibido, "
                            " org_id, created_at) "
                            "VALUES (:ca, :tc, :amb, :ruc, :rz, :fe, :fa, :it, :ea, :na, "
                            "        :ee, :as, :re, :xml, :oi, :created)"
                        ), {
                            "ca": c["clave_acceso"], "tc": c["tipo_comprobante"],
                            "amb": c["ambiente"], "ruc": c["ruc_emisor"],
                            "rz": c["razon_social_emisor"], "fe": c["fecha_emision"],
                            "fa": c["fecha_autorizacion"], "it": c["importe_total"],
                            "ea": c["estado_autorizacion"], "na": c["numero_autorizacion"],
                            "ee": c["emisor_email"], "as": c["asunto_email"],
                            "re": c["recibido_email_at"], "xml": c["xml_recibido"],
                            "oi": c["org_id"], "created": now,
                        })
                        nuevos += 1
                except Exception as e:
                    logger.error(f"persist comprobante {c.get('clave_acceso','?')}: {e}")
                    errores += 1
            return nuevos, duplicados, errores

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()

    # ─── Listar comprobantes recibidos desde la BD ────────────────
    def list_inbox(self, limit: int = 100, offset: int = 0) -> tuple[bool, str, list[dict]]:
        async def _run():
            from sqlalchemy import text as _t
            async with self.engine.begin() as c2:
                await c2.run_sync(_Base.metadata.create_all)
            async with self.engine.connect() as conn:
                rows = (await conn.execute(
                    _t("SELECT clave_acceso, tipo_comprobante, ruc_emisor, "
                       "razon_social_emisor, fecha_emision, importe_total, "
                       "estado_autorizacion, emisor_email, recibido_email_at "
                       "FROM facturapro_inbox ORDER BY created_at DESC "
                       "LIMIT :l OFFSET :o").bindparams(l=limit, o=offset))).all()
                return [dict(r._mapping) for r in rows]
        try:
            loop = asyncio.new_event_loop()
            try:
                rows = loop.run_until_complete(_run())
            finally:
                loop.close()
            return (True, f"OK — {len(rows)} comprobantes.", rows)
        except Exception as e:
            return (False, f"{e.__class__.__name__}: {e}", [])

    # ─── Consulta RUC contribuyente (catastro SRI) ────────────────
    def consultar_ruc(self, ruc: str) -> tuple[bool, str, Optional[dict]]:
        rc = RucConsultor()
        try:
            res = rc.consultar(ruc)
        except SRIServiceMaintenanceError as e:
            return (False, str(e), None)
        if res is None:
            return (False, f"No se encontró el RUC {ruc} o el servicio no responde.", None)
        return (True, f"✅ {res.get('razonSocial')} — RUC {res.get('ruc')} — Estado: {res.get('estado')}", res)
