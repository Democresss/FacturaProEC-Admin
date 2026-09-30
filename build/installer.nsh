!macro customInit
  ; Cerrar la app y su backend si están abiertos antes de instalar encima (archivos en uso).
  ; SIN «/T»: al actualizar, este instalador lo lanza la propia app y /T (todo el árbol de procesos) podía
  ; matar al instalador mismo; la actualización quedaba descargada y nunca se aplicaba.
  ; No se toca facpro-vigilante.exe (el vigilante corre desde la carpeta del usuario, no desde aquí).
  DetailPrint "Cerrando FacPro Server Manager si está abierta…"
  nsExec::ExecToLog 'taskkill /F /IM "FacturaProEC Admin.exe"'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /IM "facpro-bridge.exe"'
  Pop $0
  ; Breve pausa para que libere los handles de archivos antes de copiar
  Sleep 800
!macroend
