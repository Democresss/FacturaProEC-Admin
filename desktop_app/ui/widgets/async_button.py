"""AsyncButton — botón que ejecuta una acción en segundo plano con feedback real.

Encapsula el patrón: confirmar (opcional) → deshabilitar + spinner → ejecutar
acción en hilo daemon → reactivar + mostrar modal de éxito/error con el texto
devuelto por el `ServiceRunner` o cualquier callable. Así el usuario "ve
realmente" que pasa algo cuando pulsa (crear usuario, levantar Docker,
abrir puerto, etc.).

Uso:
    AsyncButton(parent, text="🚀 Levantar Docker",
                action=runner.launch_docker_stack,
                confirm="¿Levantar PG17+MinIO+SFTPGo en Docker?",
                ok_title="Docker Compose",
                on_done=lambda res: app.refresh_stats()).pack(...)

La acción puede:
  - retornar None      → exitosa con msg genérica
  - retornar (bool,str)→ clásico de ServiceRunner: (ok, mensaje)
  - retornar bool      → success=eso
  - levantar excepción → se reporta como error sin crashear la app
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Optional

import customtkinter as ctk

from core.async_runner import AsyncActionRunner, ActionResult, normalize_result
from ui.widgets.modal import Modal


class AsyncButton(ctk.CTkButton):
    """CTkButton ampliado con ejecución asíncrona y feedback modal."""

    def __init__(
        self,
        master,
        *,
        action: Callable[[], object],
        runner: Optional["AsyncActionRunner"] = None,
        confirm: Optional[str] = None,
        confirm_title: str = "Confirmar acción",
        dangerous: bool = False,
        ok_title: str = "Operación completada",
        error_title: str = "Error",
        warn_on_fail: bool = False,  # True → Modal.warn en lugar de error (acción esperable que falle)
        on_done: Optional[Callable[[ActionResult], None]] = None,
        always_finish: Optional[Callable[[], None]] = None,
        running_text: str = "Ejecutando…",
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self._action = action
        self._runner = runner
        self._confirm = confirm
        self._confirm_title = confirm_title
        self._dangerous = dangerous
        self._ok_title = ok_title
        self._error_title = error_title
        self._warn_on_fail = warn_on_fail
        self._on_done = on_done
        self._always_finish = always_finish
        self._running_text = running_text
        self._original_text = kwargs.get("text", "Acción")
        self._modal_handle = None

        # El comando real es el gate de confirmación; si luego se inyecta
        # el runner vía bind_runner, mantiene el mismo comando.
        self.configure(command=self._on_click)

    def bind_runner(self, runner: AsyncActionRunner):
        """Inyecta el AsyncActionRunner compartido desde AppShell.

        Es seguro llamarlo después de pack/grid (pack devuelve None).
        """
        self._runner = runner
        return self  # fluid, opcional

    # ─── Flujo ────────────────────────────────────────────────────────

    def _on_click(self):
        if self._runner is None:
            # Sin runner: ejecuta en bloqueo (sin spinner) y muestra el resultado.
            try:
                out = self._action()
                res = self._normalize(out)
            except Exception as exc:  # noqa: BLE001
                res = ActionResult(False, str(exc), error=traceback.format_exc())
            self._show_result(res)
            return

        if self._confirm is not None and self.cget("state") != "disabled":
            Modal.confirm(self.master, self._confirm_title, self._confirm,
                          on_yes=self._launch_action,
                          dangerous=self._dangerous)
            return

        self._launch_action()

    def _launch_action(self):
        if self._runner is None or self.cget("state") == "disabled":
            return
        # Estado "trabajando": botón deshabilitado + cambia texto + spinner en bar.
        try:
            self.configure(state="disabled", text=self._running_text)
        except Exception:
            pass
        self._runner.run(
            action=self._action,
            on_done=self._on_finish,
            status_msg=self._running_text,
        )

    def _on_finish(self, res: ActionResult):
        try:
            self.configure(state="normal", text=self._original_text)
        except Exception:
            pass
        self._show_result(res)
        if self._on_done is not None:
            try:
                self._on_done(res)
            except Exception:
                pass
        if self._always_finish is not None:
            try:
                self._always_finish()
            except Exception:
                pass

    def _show_result(self, res: ActionResult):
        # Mensaje vacío y éxito → no abrir modal (acción silenciosa intencional)
        if res.success and res.message == "Acción completada." and self._on_done is not None:
            return
        if res.success:
            Modal.ok(self.master, self._ok_title, res.message)
        elif self._warn_on_fail:
            Modal.warn(self.master, self._error_title, res.message)
        else:
            Modal.error(self.master, self._error_title, res.message)

    @staticmethod
    def _normalize(out: Any) -> ActionResult:
        return normalize_result(out)
