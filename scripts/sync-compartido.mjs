#!/usr/bin/env node
/* ──────────────────────────────────────────────────────────────────
 *  Copia a la app lo que comparte con el repositorio de FacturaPro:
 *    ../desktop_app                                   → desktop_app/
 *    ../FacProV2/herramientas/facpro_servidor/facpro_servidor.py
 *                                                     → python-backend/servidor/facpro_servidor.py
 *  Así GitHub puede compilar la app sin el otro repositorio.
 *  Uso:  npm run sync   (antes de un release, si cambiaste esos archivos)
 * ────────────────────────────────────────────────────────────────── */
import { cpSync, rmSync, existsSync, copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const DESKTOP = resolve(ROOT, '..', 'desktop_app');
const SERVIDOR = resolve(ROOT, '..', 'FacProV2', 'herramientas', 'facpro_servidor', 'facpro_servidor.py');

if (!existsSync(DESKTOP) || !existsSync(SERVIDOR)) {
  console.error('No encuentro ../desktop_app o ../FacProV2/herramientas/facpro_servidor: corre esto dentro de FacturaProEC/admin-electron.');
  process.exit(1);
}
rmSync(resolve(ROOT, 'desktop_app'), { recursive: true, force: true });
cpSync(DESKTOP, resolve(ROOT, 'desktop_app'), {
  recursive: true,
  filter: (src) => !/__pycache__|\.pyc$|\.log$/.test(src),
});
mkdirSync(resolve(ROOT, 'python-backend', 'servidor'), { recursive: true });
copyFileSync(SERVIDOR, resolve(ROOT, 'python-backend', 'servidor', 'facpro_servidor.py'));
console.log('✔ desktop_app y facpro_servidor.py sincronizados');
