"""ruc_consultor — consulta datos del contribuyente en el SRI por REST.

Réplica síncrona y autocontenida del método
`SRIService.obtener_datos_contribuyente` (vía endpoints REST públicos del
catastro del SRI: `srienlinea.sri.gob.ec`). Sin auth (los endpoints son
públicos). Sin dependencias de FacProV2.

Endpoint base:
    https://srienlinea.sri.gob.ec/sri-catastro-sujeto-servicio-internet/rest

Flujo:
    1. ConsolidadoContribuyente/existePorNumeroRuc?numeroRuc=RUC
    2. ConsolidadoContribuyente/obtenerPorNumerosRuc?ruc=RUC
    3. Establecimiento/consultarPorNumeroRuc?numeroRuc=RUC

Limitaciones heredadas: puede decaer a `None` si el SRI responde None,
si el contribuyente no existe, o si está en mantenimiento.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://srienlinea.sri.gob.ec/sri-catastro-sujeto-servicio-internet/rest"

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'es-ES,es;q=0.9',
    'Origin': 'https://srienlinea.sri.gob.ec',
    'Referer': 'https://srienlinea.sri.gob.ec/'
}


class SRIServiceMaintenanceError(Exception):
    """El SRI está en mantenimiento temporal."""


class RucConsultor:
    """Cliente REST síncrono del catastro del SRI."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._session: Optional[requests.Session] = None

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update(_HEADERS)
            self._session = s
        return self._session

    def validar_ruc(self, ruc: str) -> bool:
        """Validación algorítmica básica de longitud/dígitos."""
        return bool(ruc) and len(ruc) in (10, 13) and ruc.isdigit()

    def consultar(self, ruc: str) -> Optional[dict]:
        """Devuelve la ficha del contribuyente o None."""
        if not self.validar_ruc(ruc):
            return None
        try:
            # 1. existePorNumeroRuc
            url1 = f"{_BASE_URL}/ConsolidadoContribuyente/existePorNumeroRuc"
            r1 = self.session.get(url1, params={"numeroRuc": ruc}, timeout=self.timeout)

            text_lower = (r1.text or "").lower()
            if "mantenimiento" in text_lower or "no disponible" in text_lower or r1.status_code == 503:
                raise SRIServiceMaintenanceError(
                    "El servicio del SRI está en mantenimiento. Intente más tarde.")

            if r1.status_code != 200:
                return None

            try:
                existe_data = r1.json()
                if isinstance(existe_data, bool):
                    existe = existe_data
                elif isinstance(existe_data, dict):
                    existe = existe_data.get('data', True)
                else:
                    existe = True
            except Exception:
                existe = True

            if not existe:
                return None

            # 2. obtenerPorNumerosRuc
            url2 = f"{_BASE_URL}/ConsolidadoContribuyente/obtenerPorNumerosRuc"
            r2 = self.session.get(url2, params={"ruc": ruc}, timeout=self.timeout)
            if r2.status_code != 200:
                return None
            contribuyente_data = r2.json() if r2.text else {}

            # 3. consultarPorNumeroRuc (establecimientos)
            url3 = f"{_BASE_URL}/Establecimiento/consultarPorNumeroRuc"
            r3 = self.session.get(url3, params={"numeroRuc": ruc}, timeout=self.timeout)
            establecimiento_data = {}
            if r3.status_code == 200:
                try:
                    establecimiento_data = r3.json() if r3.text else {}
                except Exception:
                    pass

            # Normalizar datos
            if isinstance(contribuyente_data, list) and len(contribuyente_data) > 0:
                datos = contribuyente_data[0]
            elif isinstance(contribuyente_data, dict):
                datos = contribuyente_data.get('data', contribuyente_data)
                if isinstance(datos, list) and len(datos) > 0:
                    datos = datos[0]
            else:
                datos = {}

            razon_social = (datos.get('razonSocial') or
                            datos.get('nombreComercial') or
                            datos.get('nombre') or
                            datos.get('razon_social'))
            if not razon_social:
                return None

            resultado = {
                'ruc': ruc,
                'razonSocial': razon_social,
                'nombreComercial': datos.get('nombreComercial', razon_social),
                'estado': datos.get('estadoContribuyenteRuc', datos.get('estado', 'ACTIVO')),
                'actividadEconomica': datos.get('actividadEconomicaPrincipal'),
                'tipoContribuyente': datos.get('tipoContribuyente'),
                'obligadoContabilidad': datos.get('obligadoLlevarContabilidad'),
                'agenteRetencion': datos.get('agenteRetencion'),
                'contribuyenteEspecial': datos.get('contribuyenteEspecial'),
                'regimen': datos.get('regimen'),
                'existe': True,
            }

            # Establecimientos
            establecimientos_list = []
            if establecimiento_data:
                if isinstance(establecimiento_data, list):
                    est_list = establecimiento_data
                elif isinstance(establecimiento_data, dict):
                    est_list = establecimiento_data.get('data', [establecimiento_data])
                    if not isinstance(est_list, list):
                        est_list = [est_list]
                else:
                    est_list = []

                for est_data in est_list:
                    if isinstance(est_data, dict) and est_data:
                        establecimientos_list.append({
                            'numeroEstablecimiento': est_data.get('numeroEstablecimiento'),
                            'nombreFantasia': est_data.get('nombreFantasiaComercial'),
                            'direccion': est_data.get('direccionCompleta'),
                            'estado': est_data.get('estado'),
                            'tipo': est_data.get('tipo'),
                            'esMatriz': est_data.get('esMatriz', False),
                        })

                if establecimientos_list:
                    resultado['establecimientos'] = establecimientos_list
                    principal = next(
                        (e for e in establecimientos_list if e.get('esMatriz')),
                        establecimientos_list[0]
                    )
                    if principal:
                        resultado['establecimiento'] = principal
                        if principal.get('direccion'):
                            resultado['direccion'] = principal['direccion']

            return resultado

        except requests.Timeout:
            logger.warning(f"SRI timeout consultando {ruc}")
            return None
        except SRIServiceMaintenanceError:
            raise
        except Exception as e:
            logger.error(f"SRI consultar error: {e}")
            return None


# Singleton para reusar sesión entre consultas.
_default = RucConsultor()


def get_default() -> RucConsultor:
    return _default
