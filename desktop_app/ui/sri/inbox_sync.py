"""inbox_sync — wrapper de thread para la sincronización IMAP del módulo SRI.

`SRIFacade.sync_inbox` es síncrono (crea su propio event loop internamente),
pero puede tardar decenas de segundos scrolleando un buzón grande + parseando
XML + persistiendo en la BD. Si lo llamáramos directamente desde un callback
de customtkinter, congelaría la UI completa.

`InboxSyncWorker` lanza esa llamada en un `threading.Thread(daemon=True)` y
entrega el resultado (`SyncStats`) y el progreso (callbacks de texto por
cada comprobante parseado) al hilo de UI mediante `root.after(0, cb)`, que es
la forma segura de cruzar hilos con tkinter sin `threading.Lock`.

No depende de `AsyncActionRunner`: el srí_tab puede usar cualquiera de los
dos. Aquí elegimos un wrapper dedicado porque `sync_inbox` ya reporta
progreso granular (clave de acceso por comprobante) que conviene llevar a un
log en vivo, cosa que el AsyncActionRunner (pensado para barra indeterminada
genérica) no expone.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

from ui.sri.sri_facade import SRIFacade, SyncStats


@dataclass
class ImapParams:
    """Parámetros IMAP normalizados (se sacan del config en el sri_tab)."""
    host: str
    port: int
    user: str
    password: str
    folder: str = "INBOX"
    limit: int = 50
    org_id: str = "default"


class InboxSyncWorker:
    """Lanza `SRIFacade.sync_inbox` en un hilo daemon y reporta a la UI.

    Uso típico desde el sri_tab (en el hilo de UI):

        worker = InboxSyncWorker(
            root=self.ctx.root,
            facade=self.facade,
            on_progress=lambda clave: self.log(f"· parseado {clave}"),
            on_done=lambda stats: self._on_sync_done(stats),
        )
        worker.start(params)

    `on_progress` y `on_done` SIEMPRE se invocan en el hilo de UI (vía after),
    nunca en el worker. Si la ventana ya se cerró, se ignoran silenciosamente.
    """

    def __init__(
        self,
        root,
        facade: SRIFacade,
        on_progress: Optional[Callable[[str], None]] = None,
        on_done: Optional[Callable[[SyncStats], None]] = None,
    ):
        self.root = root
        self.facade = facade
        self._on_progress = on_progress
        self._on_done = on_done
        self._thread: Optional[threading.Thread] = None

    # ─── API pública ────────────────────────────────────────────────────

    def start(self, params: ImapParams) -> threading.Thread:
        """Arranca la sincronización en background. Devuelve el Thread."""
        if self._thread is not None and self._thread.is_alive():
            # Si ya está corriendo, no lanza otro (evita duplicar IMAP).
            return self._thread

        def _worker():
            # Puenteo de progreso: el facade llama on_progress en el hilo
            # worker; yo lo entrego al hilo de UI con root.after(0, ...).
            def _pipe(clave: str):
                if self._on_progress is None:
                    return
                try:
                    self.root.after(0, lambda c=clave: self._on_progress(c))
                except Exception:
                    pass  # ventana cerrada

            stats = self.facade.sync_inbox(
                params.host, params.port, params.user, params.password,
                folder=params.folder, limit=params.limit,
                org_id=params.org_id, on_progress=_pipe,
            )
            if self._on_done is not None:
                try:
                    self.root.after(0, lambda: self._on_done(stats))
                except Exception:
                    pass  # ventana cerrada

        t = threading.Thread(target=_worker, daemon=True,
                              name="facturapro-imap-sync")
        self._thread = t
        t.start()
        return t

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
