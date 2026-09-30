"""XmlSriParserAdapter — standalone (sin dependencias de FacProV2).

Copia autocontenida de
`FacProV2/infrastructure/adapters/xml_sri_parser_adapter.py` sin heredar
de `IXmlSriParserAdapter`. Sólo usa `xml.etree.ElementTree` (stdlib).

Parser universal de XML SRI Ecuador: detecta factura(01), notaCredito(04),
notaDebito(05), guiaRemision(06), comprobanteRetencion(07) y devuelve un
dict normalizado con claveAcceso, rucEmisor, razonSocialEmisor,
fechaEmision y total.

Extensión own (no en FacProV2): `parse_with_envelope()` detecta una
envoltura SOAP de autorización (`<autorizacion>` con `<comprobante>` en
CDATA) y desempaqueta el comprobante interno antes de parsearlo — caso
típico de facturas RECIBIDAS vía IMAP, que llegan como XML de
autorización, no como comprobante raíz. También añade `numeroAutorizacion`,
`fechaAutorizacion`, `ambiente`, `estadoAutorizacion` cuando hay envoltura.

Limitaciones heredadas del original: IVA/subtotal siempre 0 (recalcular
desde XML si se necesita más detalle).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class XmlSriParserAdapter:
    """Parser universal de XML del SRI Ecuador (standalone)."""

    def parse(self, xml_bytes: bytes) -> Optional[dict]:
        try:
            tree = ET.fromstring(xml_bytes)

            # Eliminar namespaces para facilitar parsing
            for elem in tree.iter():
                if "}" in elem.tag:
                    elem.tag = elem.tag.split("}")[1]

            # Detectar tipo
            comprobante = None
            tipo = None

            if tree.tag == "factura":
                comprobante = tree
                tipo = "01"
            elif tree.tag == "notaCredito":
                comprobante = tree
                tipo = "04"
            elif tree.tag == "notaDebito":
                comprobante = tree
                tipo = "05"
            elif tree.tag == "guiaRemision":
                comprobante = tree
                tipo = "06"
            elif tree.tag == "comprobanteRetencion":
                comprobante = tree
                tipo = "07"

            if not comprobante:
                return None

            return self._extract(comprobante, tipo)
        except Exception as e:
            logger.error(f"parse XML SRI: {e}")
            return None

    def parse_with_envelope(self, xml_bytes: bytes) -> Optional[dict]:
        """Parse robusto: si el XML es una autorización SOAP, desempaqueta
        el `<comprobante>` interno (CDADA) y luego lo parsea. Devuelve el
        comprobante normalizado MÁS los campos de autorización cuando
        estén presentes. Sino, cae a `parse()` normal.
        """
        try:
            tree = ET.fromstring(xml_bytes)
            for elem in tree.iter():
                if "}" in elem.tag:
                    elem.tag = elem.tag.split("}")[1]

            envelope = None
            if tree.tag == "autorizacion":
                envelope = tree

            if envelope is not None:
                estado = envelope.findtext("estado", "")
                numero_aut = envelope.findtext("numeroAutorizacion", "")
                fecha_aut = envelope.findtext("fechaAutorizacion", "")
                ambiente = envelope.findtext("ambiente", "")
                comp_node = envelope.find("comprobante")
                if comp_node is not None:
                    inner_text = (comp_node.text or "").strip()
                    if not inner_text:
                        #/XML de autorización SRI suele tener el comprobante en CDATA, ElementTree
                        # lo deja en .text como string plano. Si llega vacío, intentamos el tail.
                        for child in comp_node.iter():
                            if child.text and child.text.strip():
                                inner_text = child.text.strip()
                                break
                    if inner_text:
                        try:
                            inner_bytes = inner_text.encode("utf-8")
                        except Exception:
                            inner_bytes = inner_text.encode("utf-8", errors="replace")
                        res = self.parse(inner_bytes)
                        if res:
                            res["estadoAutorizacion"] = estado
                            res["numeroAutorizacion"] = numero_aut
                            res["fechaAutorizacion"] = fecha_aut
                            res["ambiente"] = ambiente
                            return res
                # Sin comprobante interno parseable → None
                return None

            # No es autorización → parse directo
            return self.parse(xml_bytes)
        except Exception as e:
            logger.error(f"parse_with_envelope XML SRI: {e}")
            # Última opción: intentar extraer comprobante por regex
            return self._regex_fallback(xml_bytes)

    def _regex_fallback(self, xml_bytes: bytes) -> Optional[dict]:
        """Fallback defensivo: si ElementTree falla por CDATA mal escapado,
        extraer con regex el primer tag <factura|notaCredito|...>."""
        try:
            text = xml_bytes.decode("utf-8", errors="replace")
            m = re.search(r"<(factura|notaCredito|notaDebito|guiaRemision|comprobanteRetencion)\b",
                          text)
            if not m:
                return None
            return self.parse(text.encode("utf-8"))
        except Exception:
            return None

    # ─── Helpers internos ──────────────────────────────────────────
    def _extract(self, comprobante, tipo: str) -> dict:
        # Extraer info tributaria
        info_trib = comprobante.find("infoTributaria")
        clave = ""
        ruc_emisor = ""
        razon_social = ""
        if info_trib is not None:
            clave = info_trib.findtext("claveAcceso", "")
            ruc_emisor = info_trib.findtext("ruc", "")
            razon_social = info_trib.findtext("razonSocial", "")

        # Extraer info del documento (varía por tipo)
        total = 0.0
        iva = 0.0
        subtotal = 0.0
        fecha_emision = ""

        info_doc = (
            comprobante.find("infoFactura")
            or comprobante.find("infoNotaCredito")
            or comprobante.find("infoNotaDebito")
            or comprobante.find("infoGuiaRemision")
            or comprobante.find("infoCompRetencion")
        )

        if info_doc is not None:
            fecha_emision = info_doc.findtext("fechaEmision", "")
            total_str = (
                info_doc.findtext("importeTotal")
                or info_doc.findtext("valorTotal")
                or "0"
            )
            total = float(total_str or "0")
            if tipo == "07":
                total = 0.0

        return {
            "claveAcceso": clave,
            "tipoComprobante": tipo,
            "rucEmisor": ruc_emisor,
            "razonSocialEmisor": razon_social,
            "fechaEmision": fecha_emision,
            "total": total,
            "iva": iva,
            "subtotal": subtotal
        }

