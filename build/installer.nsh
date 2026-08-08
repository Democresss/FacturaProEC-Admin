!macro customInit
  ; Cerrar la app si está abierta antes de instalar encima.
  ; Si el usuario instaló una versión vieja y está corriendo, esto fuerza
  ; el cierre para que los archivos (app.asar, python-runtime, etc.) se
  ; puedan sobrescribir sin "El proceso no tiene acceso al archivo".
  DetailPrint "Cerrando FacturaProEC Admin si está abierta…"
  ; Intento 1: por nombre de proceso ( productName → "FacturaProEC Admin.exe")
  nsExec::ExecToLog 'taskkill /F /IM "FacturaProEC Admin.exe" /T'
  Pop $0
  ; Intento 2: nombre alternativo ( package.json "name" )
  nsExec::ExecToLog 'taskkill /F /IM "facturaproec-admin.exe" /T'
  Pop $0
  ; Breve pausa para que libere los handles de archivos antes de copiar
  Sleep 800
!macroend
