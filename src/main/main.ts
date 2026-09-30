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
import * as crypto from 'crypto';

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let bridgeProcess: ChildProcess | null = null;
let bridgePort: number | null = null;
let isQuitting = false;
let actualizacionLista = false;   // descargada: se instala en cuanto la app quede en segundo plano
let descargando = false;
let archivoDescargado = '';   // ruta del .deb/.rpm/.exe descargado por electron-updater

// Tras instalar una actualización en segundo plano la app vuelve a abrirse igual: escondida en la bandeja.
const MARCA_OCULTA = () => path.join(app.getPath('userData'), 'arrancar-oculta');
function arrancarOculta(): boolean {
  if (process.argv.includes('--hidden')) return true;
  try {
    if (fs.existsSync(MARCA_OCULTA())) { fs.unlinkSync(MARCA_OCULTA()); return true; }
  } catch { /* noop */ }
  return false;
}
const OCULTA_AL_ARRANCAR = arrancarOculta();

// Nombre visible. El nombre interno (productName «FacturaProEC Admin») no cambia: de él dependen la carpeta de
// instalación, los datos guardados y las actualizaciones automáticas.
const NOMBRE = 'FacPro Server Manager';

const isDev = !app.isPackaged;
const ROOT = app.getAppPath();
const RESOURCES = process.resourcesPath || ROOT;

// Clave que solo conocen este proceso, el backend y la ventana: sin ella el backend responde 401.
// Antes cualquier página web abierta en el navegador podía usar el backend en 127.0.0.1.
const BRIDGE_TOKEN = crypto.randomBytes(24).toString('hex');

// AppImage en Ubuntu 24.04+ / distros con AppArmor estricto: el sandbox de Chromium no arranca sin
// permisos especiales y la app se cerraba al abrir. El .deb y el .rpm instalan el sandbox bien.
if (process.platform === 'linux' && process.env.APPIMAGE) {
  app.commandLine.appendSwitch('no-sandbox');
}

// Una sola instancia: si el icono de bandeja no se ve (algunos escritorios de Linux), volver a abrir
// la app muestra la ventana en vez de arrancar otra copia escondida.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => showMainWindow());
}

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

/**
 * Backend compilado (PyInstaller): un solo ejecutable con Python y todas sus librerías adentro.
 * Es lo que hace que la app funcione en cualquier Linux y en Windows 10/11 sin instalar nada.
 */
function resolveFrozenBridge(): string | null {
  const exe = process.platform === 'win32' ? 'facpro-bridge.exe' : 'facpro-bridge';
  const candidates = [
    path.join(RESOURCES, 'bridge', exe),           // app instalada
    path.join(ROOT, 'dist-bridge', exe),           // dev, tras compilarlo
  ];
  if (process.env.FACTURAPRO_PYTHON) return null;  // override explícito para desarrollo
  return candidates.find(c => fs.existsSync(c)) || null;
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
  //    En Linux el comando es python3 (en Ubuntu/Mint/Debian «python» no existe).
  console.log('[main] Usando python del sistema (no existe runtime embebido)');
  return process.platform === 'win32' ? 'python' : 'python3';
}

function startBridge(): Promise<number> {
  return new Promise((resolve, reject) => {
    const frozen = resolveFrozenBridge();
    const script = resolveBridgeScript();
    const pyExe = frozen || resolvePython();
    const args = frozen ? [] : [script];
    console.log(`[main] Lanzando bridge: ${pyExe} ${args.join(' ')}`);

    bridgeProcess = spawn(pyExe, args, {
      // El cwd DEBE existir físicamente en el FS. Si el script está dentro del
      // asar (path virtual), fallback a RESOURCES/python-backend (real).
      cwd: frozen ? path.dirname(frozen)
        : fs.existsSync(path.dirname(script)) ? path.dirname(script)
        : (fs.existsSync(path.join(RESOURCES, 'python-backend')) ? path.join(RESOURCES, 'python-backend')
        : process.resourcesPath || undefined),
      env: { ...process.env, BRIDGE_PORT: '0', PYTHONUNBUFFERED: '1', RESOURCES_PATH: String(RESOURCES),
             BRIDGE_TOKEN },
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
    title: NOMBRE,
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
    // Al arrancar con la sesión (--hidden) o tras actualizarse sola, queda en la bandeja; volver a abrir la app la muestra.
    if (!OCULTA_AL_ARRANCAR) mainWindow?.show();
  });

  // Minimizar a bandeja en vez de salir
  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow?.hide();
      avisoBandejaUnaVez();
      if (actualizacionLista) setTimeout(instalarSiEstaOculta, 15000);
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
    { label: `Abrir ${NOMBRE}`, click: () => showMainWindow() },
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
    { label: 'Salir (el túnel sigue; el vigilante también si lo instalaste)', click: () => quitApp() },
  ]);

  tray.setToolTip(`${NOMBRE} — trabajando en segundo plano`);
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

/* ───────────── Notifications ─────────────
 * Solo UNA notificación de Windows en toda la vida de la app: la primera vez que se cierra la ventana, para
 * explicar que sigue en la bandeja. Antes salía cada vez que se cerraba, más la de «actualización lista» en
 * cada arranque (checkForUpdatesAndNotify): cansaba. */

function avisoBandejaUnaVez() {
  const marca = path.join(app.getPath('userData'), 'aviso-bandeja-visto');
  try {
    if (fs.existsSync(marca)) return;
    fs.writeFileSync(marca, new Date().toISOString());
  } catch { return; }
  showNotification(NOMBRE, 'Sigue trabajando en segundo plano (icono de la bandeja): vigila el túnel.');
}

function showNotification(title: string, body: string) {
  try {
    if (Notification.isSupported()) {
      new Notification({ title, body }).show();
    }
  } catch { /* noop */ }
}

/* ───────────── Arranque automático ─────────────
 * Antes lo hacía el backend Python: en Windows registraba su propio ejecutable (python / backend), no la
 * app, y en Linux no hacía nada aunque decía que sí. Ahora lo hace Electron con la app real. */
function setAutostart(enable: boolean): { ok: boolean; message: string } {
  try {
    if (process.platform === 'linux') {
      const dir = path.join(app.getPath('home'), '.config', 'autostart');
      const file = path.join(dir, 'facturaproec-admin.desktop');
      if (enable) {
        fs.mkdirSync(dir, { recursive: true });
        const exec = process.env.APPIMAGE || process.execPath;
        fs.writeFileSync(file, ['[Desktop Entry]', 'Type=Application', `Name=${NOMBRE}`,
          `Exec="${exec}" --hidden`, 'Terminal=false', 'X-GNOME-Autostart-enabled=true', ''].join('\n'));
      } else if (fs.existsSync(file)) {
        fs.unlinkSync(file);
      }
    } else {
      app.setLoginItemSettings({ openAtLogin: enable, args: ['--hidden'] });
      if (process.platform === 'win32') {
        // Entrada vieja que dejaba el backend apuntando a Python: se quita.
        spawn('reg', ['delete', 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run', '/v',
                      'FacturaProECStorageManager', '/f'], { windowsHide: true }).on('error', () => {});
      }
    }
    return { ok: true, message: enable ? `${NOMBRE} arrancará al iniciar sesión (en la bandeja)`
                                       : 'Arranque automático desactivado' };
  } catch (e: any) {
    return { ok: false, message: String(e?.message || e) };
  }
}

function getAutostart(): boolean {
  try {
    if (process.platform === 'linux') {
      return fs.existsSync(path.join(app.getPath('home'), '.config', 'autostart', 'facturaproec-admin.desktop'));
    }
    return app.getLoginItemSettings({ args: ['--hidden'] }).openAtLogin;
  } catch {
    return false;
  }
}

/** Novedades de la versión nueva (el texto del release de GitHub) como lista de líneas de texto plano. */
function notasDe(info: any): string[] {
  let n = info?.releaseNotes;
  if (Array.isArray(n)) n = n.map((x: any) => x?.note || '').join('\n');
  if (typeof n !== 'string') return [];
  const texto = n.replace(/<\/(li|p|h\d)>/gi, '\n').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
  return texto.split('\n').map(l => l.replace(/^\s*(#+|[-*•])\s*/, '').replace(/\*\*/g, '').trim())
    .filter(l => l.length > 1).slice(0, 20);
}

/* ───────────── IPC handlers ───────────── */

function setupIpc() {
  ipcMain.handle('bridge:get-port', () => bridgePort);
  ipcMain.handle('bridge:get-url', () => bridgePort ? `http://127.0.0.1:${bridgePort}` : null);
  ipcMain.handle('bridge:get-token', () => BRIDGE_TOKEN);

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
  ipcMain.handle('autostart:set', (_e, enable: boolean) => setAutostart(!!enable));
  ipcMain.handle('autostart:get', () => getAutostart());
  ipcMain.handle('app:version', () => app.getVersion());

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
  ipcMain.handle('update:install', async () => {
    try {
      if (await instalarConAyudante()) { reabrirActualizada(false); return { ok: true }; }
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
 * Flujo: al arrancar y cada 4 horas, `checkForUpdates()` (sin notificación de Windows) consulta la última
 * release del repo y baja el instalador si hay versión nueva. La app casi nunca «se cierra» (vive en la bandeja),
 * así que esperar a que el usuario salga dejaba la actualización sin instalar para siempre. Ahora:
 *   - ventana abierta → el aviso ofrece «Reiniciar y actualizar» o «Más tarde»;
 *   - app en la bandeja (o al esconderla) → se instala sola en silencio y vuelve a quedar en la bandeja.
 * En Linux .deb/.rpm instalar pide la clave del sistema: ahí se instala al salir (o con el botón).
 * En dev (sin empaquetar) no hace nada.
 */

function instalacionSilenciosa(): boolean {
  return process.platform === 'win32' || (process.platform === 'linux' && !!process.env.APPIMAGE);
}

/** Linux .deb/.rpm: con el Modo administrador, el ayudante con permisos instala la actualización sin pedir la clave. */
async function instalarConAyudante(): Promise<boolean> {
  if (process.platform !== 'linux' || process.env.APPIMAGE || !archivoDescargado || !bridgePort) return false;
  try {
    const r = await fetch(`http://127.0.0.1:${bridgePort}/api/servidor/instalar-actualizacion`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Bridge-Token': BRIDGE_TOKEN },
      body: JSON.stringify({ ruta: archivoDescargado }),
    });
    const j: any = await r.json();
    if (!j?.ok) console.warn('[update] ayudante:', j?.message);
    return !!j?.ok;
  } catch (e: any) {
    console.warn('[update] ayudante no disponible:', e?.message || e);
    return false;
  }
}

function reabrirActualizada(oculta: boolean) {
  if (oculta) { try { fs.writeFileSync(MARCA_OCULTA(), '1'); } catch { /* noop */ } }
  isQuitting = true;
  stopBridge();
  app.relaunch();
  app.exit(0);
}

async function instalarSiEstaOculta() {
  if (!actualizacionLista) return;
  if (mainWindow && mainWindow.isVisible()) return;
  if (!instalacionSilenciosa()) {
    if (await instalarConAyudante()) reabrirActualizada(true);
    return;
  }
  console.log('[update] instalando en segundo plano…');
  try { fs.writeFileSync(MARCA_OCULTA(), '1'); } catch { /* noop */ }
  isQuitting = true;
  stopBridge();
  autoUpdater.quitAndInstall(true, true);
}

function buscarActualizacion() {
  autoUpdater.checkForUpdates().catch((e: any) => console.warn('[update] no se pudo revisar:', e?.message || e));
}

function setupAutoUpdater() {
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('checking-for-update', () => {
    console.log('[update] Buscando actualizaciones…');
    mainWindow?.webContents.send('update:status', { state: 'checking' });
  });
  autoUpdater.on('update-available', (info: any) => {
    console.log(`[update] Disponible v${info.version} — descargando…`);
    descargando = true;
    mainWindow?.webContents.send('update:status', { state: 'available', version: info.version, notas: notasDe(info) });
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
    mainWindow?.webContents.send('update:status', { state: 'downloaded', version: info.version, notas: notasDe(info) });
    descargando = false;
    actualizacionLista = true;
    archivoDescargado = String(info?.downloadedFile || '');
    // En la bandeja: se instala sola en silencio (sin notificación de Windows).
    setTimeout(instalarSiEstaOculta, 5000);
  });
  autoUpdater.on('error', (err: Error) => {
    console.warn('[update] error:', err?.message || err);
    // Sin internet al revisar: nada que mostrar (se reintenta en 4 horas). Solo si falló una descarga en curso.
    if (descargando) {
      descargando = false;
      mainWindow?.webContents.send('update:status', { state: 'error', message: String(err?.message || err) });
    }
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
    setTimeout(buscarActualizacion, 5000);
    setInterval(buscarActualizacion, 4 * 60 * 60 * 1000);
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
