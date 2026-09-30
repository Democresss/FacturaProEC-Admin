"""base_tab + AppContext — contrato común de las áreas de trabajo (tabs).

Cada pestaña del tabview es una clase que hereda de `TabBase` e implementa
`build(parent)`. Recibe un `AppContext` compartido con todo lo que necesita:
- `config`: ConfigManager (persistencia JSON)
- `runner`: ServiceRunner (Docker/firewall/SFTP/FTP/lockdown)
- `async_runner`: AsyncActionRunner (lanzar acciones con spinner)
- `ip`: IP local vigente
- `set_status(msg)`: actualizar la status bar
- `refresh_stats()`: forzar refresco del dashboard
- `modal`: atajos a `Modal.ok/error/warn/confirm/progress`
- `colors`: tokens Light/Dark (`c_bg_card`, `c_bg_box`, etc.)

Esto reemplaza el monolito `AppGUI` gigante y permite añadir nuevas áreas
de trabajo (DB Viewer, SRI, Security) sin tocar las existentes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Optional

import customtkinter as ctk

from core.async_runner import AsyncActionRunner
from ui.widgets.modal import Modal


# Tokens Light/Dark compartidos (idénticos a los del AppGUI original).
COLORS = SimpleNamespace(
    c_bg_card=("#FFFFFF", "#1E293B"),
    c_bg_box=("#F1F5F9", "#0F172A"),
    c_text_title=("#0F172A", "#F8FAFC"),
    c_text_sub=("#475569", "#94A3B8"),
    c_border=("#CBD5E1", "#334155"),
)


@dataclass
class AppContext:
    """Estado compartido entre AppShell y las áreas de trabajo."""
    config: Any                                  # ConfigManager
    runner: Any                                  # ServiceRunner
    async_runner: AsyncActionRunner
    ip: str
    set_status: Callable[[str], None]
    refresh_stats: Callable[..., None]
    root: ctk.CTk                               # ventana principal (para toplevels)
    is_admin: bool = False
    known_safe_ips: set = field(default_factory=set)
    security_shield_active: bool = True
    # Atajos
    modal: type = Modal


class TabBase:
    """Contrato común de un área de trabajo (tab).

    Subclases implementan `build(self, parent)` para poblar el frame del tab
    (ya creado por el tabview). El `__init__ sólo guarda el ctx`.
    """
    title: str = "Tab"
    icon: str = "📂"

    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.parent: Optional[ctk.CTkFrame] = None

    @property
    def config(self):
        return self.ctx.config

    @property
    def runner(self):
        return self.ctx.runner

    @property
    def color(self):
        return COLORS

    def status(self, msg: str):
        self.ctx.set_status(msg)

    def modal(self):
        return self.ctx.modal

    def build(self, parent: ctk.CTkBaseClass):
        raise NotImplementedError("Cada área de trabajo debe implementar build().")
