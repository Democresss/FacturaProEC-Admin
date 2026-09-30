"""app_builder — punto único de ensamblado de la app.

Llena el `TAB_REGISTRY` con las áreas de trabajo (en orden de aparición
en el tabview) y construye el `AppShell`. Mantener un único punto de ensamblado
permite que `main.py` sea trivialmente intercambiable y que añadir una nueva
área de trabajo (DB Viewer, SRI, Security…) sea sólo añadir una línea aquí.

El orden importa: coincide con la apariencia original del AppGUI:
  1. Almacenamiento & SSH
  2. Probador de Servidor Remoto
  3. Base de Datos & Docker
  4. FTP Temporal / Permanente
  5. Red Privada / VPN
  6. SRI / Recepción (Fase 2)
  7. Ciberseguridad (Fase 3)
  8. Configuración & Ciberseguridad
"""
from __future__ import annotations

from core.base_tab import TabBase
from ui.app_shell import AppShell, TAB_REGISTRY

# Importar las áreas de trabajo. El registro se llena importando el módulo
# y añadiendo la clase (no se hace en el módulo de la tab para evitar
# dependencias circulares con app_shell).
from ui.tabs.storage_tab import StorageTab
from ui.tabs.tester_tab import TesterTab
from ui.tabs.db_tab import DbTab
from ui.tabs.ftp_tab import FtpTab
from ui.tabs.vpn_tab import VpnTab
from ui.tabs.sri_tab import SriTab
from ui.tabs.security_tab import SecurityTab
from ui.tabs.config_tab import ConfigTab

# Actualizamos el registro global que consume AppShell por defecto.
TAB_REGISTRY.clear()
TAB_REGISTRY.extend([
    StorageTab,
    TesterTab,
    DbTab,
    FtpTab,
    VpnTab,
    SriTab,
    SecurityTab,
    ConfigTab,
])


def build_app() -> AppShell:
    """Crea y retorna la ventana AppShell lista para `mainloop()`."""
    return AppShell(tab_classes=TAB_REGISTRY)
