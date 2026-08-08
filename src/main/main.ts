/**
 * main.ts — Proceso principal de Electron.
 *
 * Responsabilidades:
 * 1. Lanzar el backend Python (bridge FastAPI) como child process.
 * 2. Capturar el puerto efímero que el bridge imprime en stdout.
 * 3. Crear la BrowserWindow y cargar el renderer (dev: vite, prod: dist).
 * 4. System tray + minimizar a bandeja (segundo plano).
 * 5. Auto-update (opcional, deshabilitado en dev).
 * 6. Manejar el theme nativo (Dark/Light/System) y notificar al renderer.
 * 7. Native notifications (toast) cuando el backend reporta eventos.
 */
import { app, BrowserWindow, Tray, Menu, ipcMain, nativeTheme, nativeImage, shell, Notification } from 'electron';
import { autoUpdater } from 'electron-updater';
import * as path from 'path';
import { spawn, ChildProcess } from 'child_process';
import * as fs from 'fs';

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let bridgeProcess: ChildProcess | null = null;
let bridgePort: number | null = null;
let isQuitting = false;

const isDev = !app.isPackaged;
const ROOT = app.getAppPath();
const RESOURCES = process.resourcesPath || ROOT;

/* ───────────── Backend Python (bridge FastAPI) ───────────── */

function resolveBridgeScript(): string {
  // Dev: desde el source. Prod: desde resourcesPath/python-backend.
  // IMPORTANTE: priorizar el FS real (RESOURCES/python-backend) sobre la
  // copia dentro del app.asar — porque el spawn() del backend necesita un
  // cwd que exista físicamente. app.asar/python-backend es virtual y NO se
  // puede usar como cwd de spawn (Node lanza ENOENT).
  const candidates = [
    path.join(RESOURCES, 'python-backend', 'bridge.py'),  // FS real (extraResources)
    path.join(ROOT, 'python-backend', 'bridge.py'),        // dev (ROOT = admin-electron)
    path.join(ROOT, 'resources', 'python-backend', 'bridge.py'),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  console.error('[main] bridge.py no encontrado en:', candidates);
  return candidates[0];
}

function resolvePython(): string {
  // 1. Variable de entorno explícita (override manual para dev/testing).
  if (process.env.FACTURAPRO_PYTHON) return process.env.FACTURAPRO_PYTHON;
  // 2. Runtime embebido dentro del .exe (resources/python-runtime/python.exe).
  //    En dev: ROOT/resources/python-runtime/python.exe
  //    En prod: RESOURCES_PATH/python-runtime/python.exe
  const candidates = [
    path.join(RESOURCES, 'python-runtime', 'python.exe'),
    path.join(ROOT, 'resources', 'python-runtime', 'python.exe'),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      console.log(`[main] Python embebido encontrado: ${c}`);
      return c;
    }
  }
  // 3. Fallback: python del sistema (útil en dev sin haber descargado el runtime).
  console.log('[main] Usando python del sistema (no existe runtime embebido)');
  return 'python';
}

function startBridge(): Promise<number> {
  return new Promise((resolve, reject) => {
    const script = resolveBridgeScript();
    const pyExe = resolvePython();
    console.log(`[main] Lanzando bridge: ${pyExe} ${script}`);

    bridgeProcess = spawn(pyExe, [script], {
      // El cwd DEBE existir físicamente en el FS. Si el script está dentro del
      // asar (path virtual), fallback a RESOURCES/python-backend (real).
      cwd: fs.existsSync(path.dirname(script)) ? path.dirname(script)
        : (fs.existsSync(path.join(RESOURCES, 'python-backend')) ? path.join(RESOURCES, 'python-backend')
        : process.resourcesPath || undefined),
      env: { ...process.env, BRIDGE_PORT: '0', PYTHONUNBUFFERED: '1', RESOURCES_PATH: String(RESOURCES) },
      windowsHide: true,
    });

    let resolved = false;
    const timeout = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        reject(new Error('Timeout esperando BRIDGE_PORT del backend'));
      }
    }, 30000);

    bridgeProcess.stdout?.on('data', (data: Buffer) => {
      const text = data.toString();
      process.stdout.write(`[bridge] ${text}`);
      const m = text.match(/BRIDGE_PORT=(\d+)/);
      if (m && !resolved) {
        resolved = true;
        clearTimeout(timeout);
        bridgePort = parseInt(m[1], 10);
        console.log(`[main] Bridge escuchando en http://127.0.0.1:${bridgePort}`);
        resolve(bridgePort);
      }
    });

    bridgeProcess.stderr?.on('data', (data: Buffer) => {
      process.stderr.write(`[bridge:err] ${data}`);
    });

    bridgeProcess.on('exit', (code) => {
      console.log(`[main] Bridge terminó con código ${code}`);
      bridgeProcess = null;
      bridgePort = null;
      if (!resolved) {
        resolved = true;
        clearTimeout(timeout);
        reject(new Error(`Bridge terminó antes de dar puerto (code=${code})`));
      }
    });

    bridgeProcess.on('error', (err) => {
      console.error('[main] Error lanzando bridge:', err);
      if (!resolved) {
        resolved = true;
        clearTimeout(timeout);
        reject(err);
      }
    });
  });
}

function stopBridge() {
  if (bridgeProcess) {
    try {
      bridgeProcess.kill();
    } catch { /* noop */ }
    bridgeProcess = null;
    bridgePort = null;
  }
}

/* ───────────── Ventana principal ───────────── */

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 980,
    minHeight: 640,
    show: false,
    backgroundColor: '#0f172a',
    title: 'FacturaProEC Admin',
    icon: resolveIcon(),
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:3000');
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    // En el asar, __dirname = <ROOT>/dist/main. El renderer vive en <ROOT>/dist/renderer.
    // Subimos 1 nivel (a dist/) y bajamos a renderer/ — NO 2 niveles (eso salta dist/ y falla).
    // Usamos app.getAppPath() como ancla absoluta para no adivinar con ..
    const rendererPath = path.join(app.getAppPath(), 'dist', 'renderer', 'index.html');
    console.log(`[main] loadFile → ${rendererPath}  (exists? ${fs.existsSync(rendererPath)})`);
    mainWindow.loadFile(rendererPath);
    // En producción: si el renderer falla al cargar o entra en error,
    // abrir DevTools para poder diagnosticar (se cierra con Ctrl+W o F12).
    mainWindow.webContents.on('did-fail-load', (_e, code, desc, url) => {
      console.error(`[renderer] did-fail-load code=${code} desc=${desc} url=${url}`);
      if (!mainWindow?.webContents.isDevToolsOpened()) {
        mainWindow?.webContents.openDevTools({ mode: 'detach' });
      }
    });
    mainWindow.webContents.on('console-message', (_e, level, message, line, sourceId) => {
      const lvl = ['log', 'warn', 'error'][level] || 'log';
      console.log(`[renderer:${lvl}] ${message}  (${sourceId}:${line})`);
    });
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();
  });

  // Minimizar a bandeja en vez de salir
  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow?.hide();
      showNotification('FacturaProEC Admin', 'La app sigue corriendo en segundo plano (icono de bandeja).');
    }
  });

  // Abrir links externos en navegador del sistema
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

/* ───────────── Iconos ───────────── */

function resolveIcon(): string {
  const ext = process.platform === 'win32' ? 'ico'
    : process.platform === 'darwin' ? 'icns' : 'png';
  const candidates = [
    path.join(RESOURCES, 'resources', 'icons', `icon.${ext}`),
    path.join(ROOT, 'resources', 'icons', `icon.${ext}`),
    path.join(ROOT, 'resources', 'icons', 'icon.png'),
  ];
  return candidates.find(p => fs.existsSync(p)) || candidates[0];
}

function resolveTrayIcon() {
  const png = process.platform === 'darwin'
    ? path.join(RESOURCES, 'resources', 'icons', 'icon.png')
    : resolveIcon();
  // Tray en macOS prefiere PNG; en Windows acepta ico.
  const trayPng = path.join(RESOURCES, 'resources', 'icons', 'icon.png');
  if (fs.existsSync(trayPng)) return trayPng;
  return png;
}

/* ───────────── Tray ───────────── */

function createTray() {
  const iconPath = resolveTrayIcon();
  const img = nativeImage.createFromPath(iconPath);
  tray = new Tray(img.isEmpty() ? nativeImage.createEmpty() : img);

  const menu = Menu.buildFromTemplate([
    { label: 'Mostrar FacturaProEC', click: () => showMainWindow() },
    { type: 'separator' },
    {
      label: 'Tema',
      submenu: [
        { label: 'Sistema', type: 'radio', click: () => setTheme('system') },
        { label: 'Claro', type: 'radio', click: () => setTheme('light') },
        { label: 'Oscuro', type: 'radio', click: () => setTheme('dark') },
      ],
    },
    { type: 'separator' },
    { label: 'Salir', click: () => quitApp() },
  ]);

  tray.setToolTip('FacturaProEC Admin');
  tray.setContextMenu(menu);
  tray.on('click', () => showMainWindow());
}

function showMainWindow() {
  if (!mainWindow) {
    createWindow();
  } else {
    mainWindow.show();
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
}

function quitApp() {
  isQuitting = true;
  stopBridge();
  tray?.destroy();
  tray = null;
  mainWindow?.destroy();
  app.quit();
}

/* ───────────── Theme ───────────── */

function setTheme(mode: 'system' | 'light' | 'dark') {
  nativeTheme.themeSource = mode;
  mainWindow?.webContents.send('theme:changed', { mode, effective: nativeTheme.shouldUseDarkColors ? 'dark' : 'light' });
}

nativeTheme.on('updated', () => {
  const effective = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
  mainWindow?.webContents.send('theme:system-changed', { effective });
});

/* ───────────── Notifications ───────────── */

function showNotification(title: string, body: string) {
  try {
    if (Notification.isSupported()) {
      new Notification({ title, body }).show();
    }
  } catch { /* noop */ }
}

/* ───────────── IPC handlers ───────────── */

function setupIpc() {
  ipcMain.handle('bridge:get-port', () => bridgePort);
  ipcMain.handle('bridge:get-url', () => bridgePort ? `http://127.0.0.1:${bridgePort}` : null);

  ipcMain.handle('theme:set', (_e, mode: 'system'|'light'|'dark') => {
    setTheme(mode);
    return { mode, effective: nativeTheme.shouldUseDarkColors ? 'dark' : 'light' };
  });
  ipcMain.handle('theme:get', () => ({
    source: nativeTheme.themeSource,
    effective: nativeTheme.shouldUseDarkColors ? 'dark' : 'light',
  }));

  ipcMain.handle('app:minimize-to-tray', () => {
    mainWindow?.hide();
  });

  ipcMain.handle('app:quit', () => quitApp());

  ipcMain.handle('notify', (_e, title: string, body: string) => {
    showNotification(title, body);
  });

  // Open external links
  ipcMain.handle('shell:open', (_e, url: string) => shell.openExternal(url));

  // Auto-update API expuesta al renderer
  ipcMain.handle('update:check', async () => {
    try {
      const info = await autoUpdater.checkForUpdates();
      return { ok: true, version: info?.updateInfo?.version || null };
    } catch (e: any) {
      return { ok: false, message: String(e?.message || e) };
    }
  });
  ipcMain.handle('update:install', () => {
    try {
      autoUpdater.quitAndInstall();
      return { ok: true };
    } catch (e: any) {
      return { ok: false, message: String(e?.message || e) };
    }
  });

  // Guarda el config del bridge en disco (persistencia extra fuera del bridge)
  // No es necesario: el bridge ya persiste su config.json.
}

/* ───────────── Auto-updater (electron-updater) ─────────────
 *
 * El repo de GitHub se configura en package.json → build.publish
 * (github provider). electron-updater lo lee automáticamente.
 *
 * Flujo: al arrancar la app empaquetada, `checkForUpdatesAndNotify()`
 * consulta la última release del repo, baja el .exe si hay versión
 * nueva, y al cerrar la app la instala. En dev (sin empaquetar) no
 * hace nada (autoUpdater no tiene channel).
 */

function setupAutoUpdater() {
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('checking-for-update', () => {
    console.log('[update] Buscando actualizaciones…');
    mainWindow?.webContents.send('update:status', { state: 'checking' });
  });
  autoUpdater.on('update-available', (info: any) => {
    console.log(`[update] Disponible v${info.version} — descargando…`);
    mainWindow?.webContents.send('update:status', { state: 'available', version: info.version });
    // No usamos Notification del SO para updates: el renderer muestra un modal
    // con barra de progreso dentro de la app. Solo avisamos por SO si la app
    // está minimizada a bandeja (para no romper la UX).
  });
  autoUpdater.on('update-not-available', () => {
    console.log('[update] Sin actualizaciones (al día).');
    mainWindow?.webContents.send('update:status', { state: 'up-to-date' });
  });
  autoUpdater.on('download-progress', (p: any) => {
    // Enviar percent Y también el estado (para que el modal cambie a "descargando")
    mainWindow?.webContents.send('update:progress', { percent: Math.round(p.percent) });
  });
  autoUpdater.on('update-downloaded', (info: any) => {
    console.log(`[update] v${info.version} descargada — reiniciar para instalar.`);
    mainWindow?.webContents.send('update:status', { state: 'downloaded', version: info.version });
    // Si la ventana está oculta (minimizada a bandeja), avisar por SO una sola vez.
    if (!mainWindow || !mainWindow.isVisible()) {
      showNotification('Actualización lista', `Reinicia para instalar v${info.version}.`);
    }
  });
  autoUpdater.on('error', (err: Error) => {
    console.warn('[update] error:', err?.message || err);
    mainWindow?.webContents.send('update:status', { state: 'error', message: String(err?.message || err) });
  });
}

/* ───────────── App lifecycle ───────────── */

app.whenReady().then(async () => {
  try {
    bridgePort = await startBridge();
    console.log(`[main] Bridge arrancó en puerto ${bridgePort}`);
  } catch (err) {
    console.error('[main] No se pudo arrancar el backend Python:', err);
    // Mostrar ventana de error al renderer de todas formas
  }

  setupIpc();
  setupAutoUpdater();
  createWindow();
  createTray();

  // Comprobar actualizaciones (solo en app empaquetada; en dev no hace nada)
  if (app.isPackaged) {
    setTimeout(() => {
      try {
        autoUpdater.checkForUpdatesAndNotify();
      } catch (e) {
        console.warn('[update] checkForUpdates falló:', e);
      }
    }, 5000);
  }
});

app.on('window-all-closed', () => {
  // En macOS la app sigue en el dock; en otros, si hay tray, no salir.
  if (process.platform !== 'darwin' && !tray) {
    quitApp();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on('before-quit', () => {
  isQuitting = true;
});

process.on('exit', () => stopBridge());
process.on('SIGINT', () => quitApp());
process.on('SIGTERM', () => quitApp());
