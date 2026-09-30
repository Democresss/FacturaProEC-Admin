"""Modal — fábrica de modales reactivos en customtkinter.

Reemplaza los `messagebox.showinfo/showwarning/showerror/askyesno` nativos
por diálogos consistentes, basados en la plantilla amarilla/roja que ya
usaba `AppGUI.show_ftp_vpn_connection_error_modal`. Esto da feedback
visual coherente cuando se "mete algo", se "crea" o se "falla".

API:
    Modal.ok(parent, "Título", "Mensaje")
    Modal.error(parent, "Título", "Mensaje")
    Modal.warn(parent, "Título", "Mensaje")
    Modal.confirm(parent, "Título", "Mensaje", on_yes=lambda: ...)
    Modal.confirm(parent, "Confirmar cerrojo", "…", on_yes=self.lockdown, dangerous=True)
    handle = Modal.progress(parent, "Sincronizando…")
        handle.update(pct_0_a_1, "Texto")   # determinate
        o      handle.update(None, "Texto")  # indeterminate
        handle.done()                        # cierra y llama on_done(opt)

Todos son CTkToplevel con grab_set y centrado sobre `parent`.
"""
from __future__ import annotations

import customtkinter as ctk
from typing import Callable, Optional


# ─── Paleta compartida (alineada con la del modal original) ───────────
_OK_GREEN = ("#16A34A", "#10B981")
_OK_GREEN_FG = "#10B981"
_OK_GREEN_HOVER = "#059669"
_WARN_YELLOW_BG = "#FEF08A"
_WARN_BORDER = "#DC2626"
_ERR_RED_TITLE = "#991B1B"
_ERR_AMBER_TEXT = "#854D0E"
_NEUTRAL_FG = "#475569"
_NEUTRAL_HOVER = "#334155"


def _center_over(parent, modal, w, h):
    try:
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (w // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (h // 2)
        modal.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
    except Exception:
        pass


def _base_toplevel(parent, title, w, h, *, resizable=False):
    modal = ctk.CTkToplevel(parent)
    modal.title(title)
    modal.geometry(f"{w}x{h}")
    modal.resizable(resizable, resizable)
    modal.transient(parent)
    try:
        modal.grab_set()
    except Exception:
        pass
    _center_over(parent, modal, w, h)
    return modal


# ─── API pública ──────────────────────────────────────────────────────

class Modal:
    """Fábrica estática de modales. No se instancia."""

    # ── OK / Éxito (verde) ─────────────────────────────────────────────
    @staticmethod
    def ok(parent, title: str, message: str, *, on_close: Optional[Callable] = None,
           close_label: str = "Aceptar", w: int = 460, h: int = 240):
        modal = _base_toplevel(parent, f"✅ {title}", w, h)
        banner = ctk.CTkFrame(modal, fg_color=("white", "#1E293B"),
                              border_color=_OK_GREEN, border_width=2, corner_radius=12)
        banner.pack(expand=True, fill="both", padx=16, pady=16)

        header = ctk.CTkFrame(banner, fg_color="transparent")
        header.pack(anchor="w", padx=16, pady=(16, 8))
        ctk.CTkLabel(header, text="✅", font=ctk.CTkFont(size=26)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=_OK_GREEN if isinstance(_OK_GREEN, str) else _OK_GREEN[1]).pack(side="left")

        ctk.CTkLabel(banner, text=message, font=ctk.CTkFont(size=12, weight="bold"),
                     wraplength=w - 80, justify="left",
                     text_color=("black", "#F8FAFC")).pack(anchor="w", padx=16, pady=(0, 16))

        btn_row = ctk.CTkFrame(banner, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(btn_row, text=close_label, fg_color=_OK_GREEN_FG,
                      hover_color=_OK_GREEN_HOVER, text_color="#FFFFFF",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: _close(modal, on_close)).pack(side="left")
        return modal

    # ── Error (plantilla amarilla/roja del modal original) ─────────────
    @staticmethod
    def error(parent, title: str, message: str, *, on_close: Optional[Callable] = None,
              retry_cb: Optional[Callable] = None, w: int = 540, h: int = 290):
        modal = _base_toplevel(parent, f"⚠️ {title}", w, h)
        banner = ctk.CTkFrame(modal, fg_color=_WARN_YELLOW_BG,
                              border_color=_WARN_BORDER, border_width=3,
                              corner_radius=12)
        banner.pack(expand=True, fill="both", padx=16, pady=16)

        header = ctk.CTkFrame(banner, fg_color="transparent")
        header.pack(anchor="w", padx=16, pady=(16, 8))
        ctk.CTkLabel(header, text="🔺", font=ctk.CTkFont(size=28)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=_ERR_RED_TITLE).pack(side="left")

        ctk.CTkLabel(banner, text=message, font=ctk.CTkFont(size=12, weight="bold"),
                     wraplength=w - 80, justify="left",
                     text_color=_ERR_AMBER_TEXT).pack(anchor="w", padx=16, pady=(0, 16))

        btn_row = ctk.CTkFrame(banner, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))
        if retry_cb is not None:
            ctk.CTkButton(btn_row, text="🔁 Reintentar", fg_color="#D97706",
                          hover_color="#B45309", text_color="#FFFFFF",
                          font=ctk.CTkFont(size=12, weight="bold"),
                          command=lambda: _close(modal) or retry_cb()).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_row, text="❌ Cerrar", fg_color=_NEUTRAL_FG,
                      hover_color=_NEUTRAL_HOVER, text_color="#FFFFFF",
                      command=lambda: _close(modal, on_close)).pack(side="left")
        return modal

    # ── Warning (ámbar, sin bloquear tanto como error) ──────────────────
    @staticmethod
    def warn(parent, title: str, message: str, *, on_close: Optional[Callable] = None,
             w: int = 460, h: int = 240):
        modal = _base_toplevel(parent, f"⚠️ {title}", w, h)
        banner = ctk.CTkFrame(modal, fg_color=("#FFF7ED", "#1E293B"),
                              border_color="#F59E0B", border_width=2, corner_radius=12)
        banner.pack(expand=True, fill="both", padx=16, pady=16)
        header = ctk.CTkFrame(banner, fg_color="transparent")
        header.pack(anchor="w", padx=16, pady=(16, 8))
        ctk.CTkLabel(header, text="⚠️", font=ctk.CTkFont(size=26)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#B45309").pack(side="left")
        ctk.CTkLabel(banner, text=message, font=ctk.CTkFont(size=12, weight="bold"),
                     wraplength=w - 80, justify="left",
                     text_color=("black", "#F8FAFC")).pack(anchor="w", padx=16, pady=(0, 16))
        btn_row = ctk.CTkFrame(banner, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(btn_row, text="Aceptar", fg_color="#D97706",
                      hover_color="#B45309", text_color="#FFFFFF",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: _close(modal, on_close)).pack(side="left")
        return modal

    # ── Confirmación (Sí / No) ─────────────────────────────────────────
    @staticmethod
    def confirm(parent, title: str, message: str, *,
                on_yes: Optional[Callable] = None,
                on_no: Optional[Callable] = None,
                yes_label: str = "Sí, continuar",
                no_label: str = "Cancelar",
                dangerous: bool = False,
                w: int = 480, h: int = 240):
        modal = _base_toplevel(parent, f"🔐 {title}", w, h)
        accent = "#DC2626" if dangerous else "#0284C7"
        accent_hover = "#991B1B" if dangerous else "#0369A1"
        banner = ctk.CTkFrame(modal, fg_color=("white", "#1E293B"),
                              border_color=accent, border_width=2, corner_radius=12)
        banner.pack(expand=True, fill="both", padx=16, pady=16)
        icon = "🔒" if dangerous else "❓"
        header = ctk.CTkFrame(banner, fg_color="transparent")
        header.pack(anchor="w", padx=16, pady=(16, 8))
        ctk.CTkLabel(header, text=icon, font=ctk.CTkFont(size=24)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=accent).pack(side="left")
        ctk.CTkLabel(banner, text=message, font=ctk.CTkFont(size=12, weight="bold"),
                     wraplength=w - 80, justify="left",
                     text_color=("black", "#F8FAFC")).pack(anchor="w", padx=16, pady=(0, 16))
        btn_row = ctk.CTkFrame(banner, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(btn_row, text=yes_label, fg_color=accent,
                      hover_color=accent_hover, text_color="#FFFFFF",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: _close(modal, on_yes)).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_row, text=no_label, fg_color=_NEUTRAL_FG,
                      hover_color=_NEUTRAL_HOVER, text_color="#FFFFFF",
                      command=lambda: _close(modal, on_no)).pack(side="left")
        return modal

    # ── Progreso determinado/indeterminado con handle vivo ────────────
    @staticmethod
    def progress(parent, title: str, *, indeterminate: bool = True,
                 w: int = 420, h: int = 200):
        modal = _base_toplevel(parent, title, w, h, resizable=False)
        container = ctk.CTkFrame(modal, fg_color=("white", "#1E293B"),
                                 corner_radius=12)
        container.pack(expand=True, fill="both", padx=16, pady=16)
        ctk.CTkLabel(container, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=("black", "#F8FAFC")).pack(anchor="w", padx=12, pady=(12, 8))
        bar = ctk.CTkProgressBar(container, height=14)
        bar.pack(fill="x", padx=12, pady=8)
        label = ctk.CTkLabel(container, text="Trabajando…",
                             font=ctk.CTkFont(size=11), wraplength=w - 80,
                             text_color=("black", "#94A3B8"), justify="left")
        label.pack(anchor="w", padx=12, pady=(4, 12))
        if indeterminate:
            try:
                bar.configure(mode="indeterminate")
                bar.start()
            except Exception:
                pass
        else:
            bar.set(0)
        return ProgressHandle(modal, bar, label, mode_indeterminate=indeterminate)


class ProgressHandle:
    """Handle de un modal de progreso. Permite actualizar y cerrar."""

    def __init__(self, modal, bar, label, *, mode_indeterminate: bool):
        self._modal = modal
        self._bar = bar
        self._label = label
        self._mode_indeterminate = mode_indeterminate
        self._closed = False

    def update(self, pct: Optional[float], text: Optional[str] = None):
        """pct: 0..1 para determinate; None mantiene indeterminate animándose."""
        if self._closed:
            return
        try:
            if pct is not None and self._mode_indeterminate:
                try:
                    self._bar.stop()
                except Exception:
                    pass
                try:
                    self._bar.configure(mode="determinate")
                except Exception:
                    pass
                self._mode_indeterminate = False
            if pct is not None:
                self._bar.set(max(0.0, min(1.0, float(pct))))
            if text is not None:
                self._label.configure(text=text)
        except Exception:
            pass

    def done(self, *, on_close: Optional[Callable] = None):
        if self._closed:
            return
        try:
            if self._mode_indeterminate:
                try:
                    self._bar.stop()
                except Exception:
                    pass
        except Exception:
            pass
        _close(self._modal, on_close)


def _close(modal, after: Optional[Callable] = None):
    """Cierra y opcionalmente dispara callback post-cierre en el hilo UI."""
    try:
        modal.grab_release()
    except Exception:
        pass
    try:
        modal.destroy()
    except Exception:
        pass
    if after is not None:
        try:
            after()
        except Exception:
            pass
