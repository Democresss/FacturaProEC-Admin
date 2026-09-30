import sys
import os
import ctypes

def is_admin():
    """Verifica si la aplicación tiene privilegios de Administrador en Windows"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def elevate_admin():
    """Solicita elevación UAC de Administrador si no se ejecuta como tal"""
    if sys.platform == 'win32' and not is_admin():
        try:
            exe = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
            args = " ".join([f'"{a}"' for a in sys.argv[1:]])
            ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
            if ret > 32:
                sys.exit(0) # Salir del proceso secundario sin elevación
        except Exception as e:
            print("No se pudo elevar a Administrador:", e)

def main():
    elevate_admin()

    # Directorio de la app en sys.path para imports absolutos
    # (from core.app_builder import build_app) — script y PyInstaller.
    app_dir = os.path.dirname(os.path.abspath(__file__))
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    from core.app_builder import build_app
    app = build_app()
    if "--minimized" in sys.argv:
        app.iconify()
    app.mainloop()

if __name__ == "__main__":
    main()
