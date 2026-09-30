"""AsyncActionRunner — motor de feedback real en customtkinter.

Lanza acciones potencialmente largas (Docker, firewall, queries SQL, SFTP,
sincronización IMAP) en un hilo daemon y muestra feedback visual mientras
se ejecutan: barra de progreso indeterminada en la status bar y estado
textual. El resultado se entrega al hilo de UI mediante `widget.after(0,…)`
para no tocar tkinter desde un hilo que no sea el principal.

Esto resuelve el problema del .exe anterior, donde cada acción callaba
mientras corría en subprocess síncrono: ahora el usuario "ve" que pasa
algo cuando mete datos o crea algo.
"""
from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ActionResult:
    """Resultado estándar de una acción asíncrona."""
    success: bool
    message: str
    data: Any = None
    error: Optional[str] = None


class AsyncActionRunner:
    """Ejecuta acciones en un hilo daemon y reporta progreso a la UI.

    Patrón de uso:
        runner = AsyncActionRunner(parent_widget, status_label, progress_bar)
        runner.run(
            action=lambda: service.launch_docker_stack(),
            on_done=lambda res: Modal.ok(parent, "Docker", res.message) if res.success
                                else Modal.error(parent, "Docker", res.message),
        )

    El callback `on_done` SIEMPRE se invoca en el hilo de UI (vía `after`),
    incluso si la acción lanza una excepción.
    """

    def __init__(self, root, status_label=None, progress_bar=None):
        """root: widget raíz de tkinter (CTk) — se usa para `after(0, cb)`.
        status_label: CTkLabel para `set_status` durante la acción.
        progress_bar: CTkProgressBar que se pone indeterminate al lanzar.
        """
        self.root = root
        self.status_label = status_label
        self.progress_bar = progress_bar
        self._active_threads: list[threading.Thread] = []

    # ─── API pública ────────────────────────────────────────────────────

    def run(
        self,
        action: Callable[[], Any],
        on_done: Optional[Callable[[ActionResult], None]] = None,
        status_msg: Optional[str] = None,
    ) -> threading.Thread:
        """Lanza `action` en un hilo daemon. Devuelve el Thread.

        `action` puede retornar:
          - None               → ActionResult(success=True, message="Completado")
          - bool               → ActionResult con success=ese bool y msg genérica
          - (bool, str)        → ActionResult(success=bool, message=str)
          - ActionResult       → se usa tal cual
          - cualquier otra cosa → ActionResult(success=True, data=<eso>)
        Cualquier excepción se captura y produce ActionResult(success=False),
        llegando igualmente a `on_done`.
        """
        self._set_running(True, status_msg or "Ejecutando acción…")

        def _worker():
            res: ActionResult
            try:
                out = action()
                res = self._normalize(out)
            except Exception as exc:  # noqa: BLE001 — captura genérica intencional
                res = ActionResult(
                    success=False,
                    message=f"Error inesperado: {exc}",
                    error=traceback.format_exc(),
                )
            # Devolver al hilo de UI
            try:
                self.root.after(0, lambda: self._finish(res, on_done))
            except Exception:
                # Si la ventana ya se cerró, no podemos llamar after; ignora.
                self._set_running(False)

        t = threading.Thread(target=_worker, daemon=True)
        self._active_threads.append(t)
        t.start()
        return t

    # ─── Helpers internos ───────────────────────────────────────────────

    def _normalize(self, out: Any) -> ActionResult:
        return normalize_result(out)

    def _set_running(self, running: bool, status_msg: Optional[str] = None):
        """Activa/desactiva el feedback visual. Llamar siempre desde el hilo UI."""
        try:
            if self.progress_bar is not None:
                if running:
                    self.progress_bar.set(0)
                    try:
                        self.progress_bar.configure(mode="indeterminate")
                        self.progress_bar.start()
                    except Exception:
                        pass
                else:
                    try:
                        self.progress_bar.stop()
                    except Exception:
                        pass
                    try:
                        self.progress_bar.configure(mode="determinate")
                    except Exception:
                        pass
                    self.progress_bar.set(0)
            if status_msg and self.status_label is not None:
                self.status_label.configure(text=status_msg)
            # Limpieza ligera de hilos terminados
            self._active_threads = [t for t in self._active_threads if t.is_alive()]
        except Exception:
            pass

    def _finish(self, res: ActionResult, on_done: Optional[Callable[[ActionResult], None]]):
        """Se ejecuta en el hilo de UI cuando la acción ha terminado."""
        self._set_running(False)
        if on_done is not None:
            try:
                on_done(res)
            except Exception as exc:  # noqa: BLE001
                # El callback del cliente no debe romper el loop de UI
                try:
                    if self.status_label is not None:
                        self.status_label.configure(text=f"Error en callback: {exc}")
                except Exception:
                    pass

    # ─── Utilidades estáticas (para uso fuera del patrón run) ──────────

    @staticmethod
    def is_busy(thread: Optional[threading.Thread]) -> bool:
        return thread is not None and thread.is_alive()


# ─── Helper de módulo (compartible con AsyncButton sin event loop) ───

def normalize_result(out: Any) -> ActionResult:
    """Convierte el valor de retorno de una `action` en un ActionResult."""
    if out is None:
        return ActionResult(True, "Acción completada.")
    if isinstance(out, ActionResult):
        return out
    if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], bool):
        return ActionResult(success=out[0], message=str(out[1]))
    if isinstance(out, bool):
        return ActionResult(
            success=out,
            message="Acción completada." if out else "Acción fallida.",
        )
    return ActionResult(True, "Acción completada.", data=out)
