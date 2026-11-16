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

!macro customInstall
  DetailPrint "Activando Modo Administrador y Piloto Automático 24/7 en Windows…"
  ; 0. Quitar marcas heredadas RUNASADMIN (el vigilante SYSTEM + tarea programada evitan ventanas UAC al abrir)
  DeleteRegValue HKCU "Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers" "$INSTDIR\FacturaProEC Admin.exe"
  DeleteRegValue HKCU "Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers" "$LOCALAPPDATA\Programs\FacturaProEC Admin\FacturaProEC Admin.exe"
  DeleteRegValue HKLM "Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers" "$INSTDIR\FacturaProEC Admin.exe"
  ; 1. Permisos de Docker sin pedir clave (grupo docker-users + servicio automático iniciado)
  nsExec::ExecToLog 'cmd.exe /c net localgroup docker-users "%USERNAME%" /add'
  Pop $0
  nsExec::ExecToLog 'sc config com.docker.service start= auto'
  Pop $0
  nsExec::ExecToLog 'sc start com.docker.service'
  Pop $0

  ; 2. Reglas de Firewall de Windows para PostgreSQL (5432), MinIO (9000) y SSH SIACI (22)
  nsExec::ExecToLog 'netsh advfirewall firewall add rule name="FacPro-PostgreSQL-5432" dir=in action=allow protocol=TCP localport=5432'
  Pop $0
  nsExec::ExecToLog 'netsh advfirewall firewall add rule name="FacPro-MinIO-9000" dir=in action=allow protocol=TCP localport=9000'
  Pop $0
  nsExec::ExecToLog 'netsh advfirewall firewall add rule name="FacPro-SSH-22" dir=in action=allow protocol=TCP localport=22'
  Pop $0

  ; 3. Ejecutar --modo-admin durante la instalación (registra Tarea SYSTEM al encender la PC + desbloquea SIACI)
  IfFileExists "$INSTDIR\resources\python-runtime\python.exe" 0 +4
    nsExec::ExecToLog '"$INSTDIR\resources\python-runtime\python.exe" "$INSTDIR\resources\python-backend\servidor\facpro_servidor.py" --modo-admin'
    Pop $0
    Goto facpro_admin_listo
  IfFileExists "$INSTDIR\resources\bridge\facpro-bridge.exe" 0 +3
    nsExec::ExecToLog '"$INSTDIR\resources\bridge\facpro-bridge.exe" --modo-admin'
    Pop $0
  facpro_admin_listo:

  ; 4. Tarea programada elevada al iniciar sesión (arranca oculto en bandeja SIN ventana UAC)
  nsExec::ExecToLog 'schtasks /Create /TN "FacPro Server Manager" /TR "\"$INSTDIR\FacturaProEC Admin.exe\" --hidden" /SC ONLOGON /RL HIGHEST /F'
  Pop $0
  ; 5. Desbloquear lectura y ejecución de tareas SYSTEM (FacPro Vigilante, FacPro Server Manager y FacPro SIACI*)
  nsExec::ExecToLog 'icacls "$WINDIR\System32\Tasks\FacPro*" /grant "*S-1-5-11:(RX)" "*S-1-5-32-545:(RX)"'
  Pop $0
  ; 6. Activar ejecución inmediata del Vigilante SYSTEM 24/7
  nsExec::ExecToLog 'schtasks /Run /TN "FacPro Vigilante"'
  Pop $0
!macroend
