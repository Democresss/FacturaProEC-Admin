"""Card — frame decorativo reutilizable, mismo look que las cards del dashboard.

Encapsula el patrón de CTkFrame con border/border_radius que aparece por
toda la app original (storage card, status card,FTP box, etc.), usando los
mismos tokens de color Light/Dark del `AppGUI` original.
"""
from __future__ import annotations

from typing import Tuple

import customtkinter as ctk

# Tokens Light/Dark idénticos a los del AppGUI original.
TOKEN_BG_CARD: Tuple[str, str] = ("#FFFFFF", "#1E293B")
TOKEN_BG_BOX: Tuple[str, str] = ("#F1F5F9", "#0F172A")
TOKEN_BORDER: Tuple[str, str] = ("#CBD5E1", "#334155")

TOKEN_TEXT_TITLE: Tuple[str, str] = ("#0F172A", "#F8FAFC")
TOKEN_TEXT_SUB: Tuple[str, str] = ("#475569", "#94A3B8")


def card(master, *, title: str = "", subtitle: str = "",
         bg: Tuple[str, str] = TOKEN_BG_BOX,
         border: Tuple[str, str] = TOKEN_BORDER,
         corner_radius: int = 10, border_width: int = 1,
         pad_y: int = 8, pad_x: int = 16) -> ctk.CTkFrame:
    """Devuelve un CTkFrame con estilo 'card' (opcionalmente con título/sub).

    El llamador puede empaquetar dentro de él otros widgets; esta función
    sólo crea el contenedor estilizado.
    """
    frame = ctk.CTkFrame(master, fg_color=bg, border_color=border,
                         border_width=border_width, corner_radius=corner_radius)
    frame.pack(fill="x", padx=pad_x, pady=pad_y)
    if title:
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TOKEN_TEXT_SUB).pack(anchor="w", padx=12, pady=(10, 2))
    if subtitle:
        ctk.CTkLabel(frame, text=subtitle, font=ctk.CTkFont(size=11),
                     text_color=TOKEN_TEXT_SUB).pack(anchor="w", padx=12, pady=(0, 8))
    return frame
