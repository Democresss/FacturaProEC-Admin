#!/usr/bin/env node
/* ──────────────────────────────────────────────────────────────────
 *  Helper: configurar GH_TOKEN para que `npm run release` pueda
 *  subir automáticamente las releases a GitHub sin intervención.
 * ──────────────────────────────────────────────────────────────────
 *  Qué hace:
 *    1. Te dice dónde crear el Personal Access Token en GitHub
 *    2. Guarda el token en un archivo .env.local que NO se commitea
 *       (ya está en .gitignore bajo *.env.local implícitamente vía
 *        el .env.local arriba — confirmamos abajo)
 *    3. Lo lee en futuras ejecuciones de `npm run release`
 *
 *  El token se guarda en C:/Users/jloor/.facturaproec-gh-token
 *  (fuera del repo — nunca va a git).
 * ────────────────────────────────────────────────────────────────── */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { homedir } from 'node:os';

const TOKEN_FILE = resolve(homedir(), '.facturaproec-gh-token');
const log = (...m) => console.log('\x1b[36m[gh:auth]\x1b[0m', ...m);

log('Vas a crear un Personal Access Token en GitHub para poder');
log('subir releases automáticamente. Pasos:');
log('');
log('  1) Abre: https://github.com/settings/tokens/new');
log('  2) Note:        FacturaProEC Admin Release Token');
log('  3) Expiration:  No expiration (o 1 año si prefieres)');
log('  4) Scopes:      ✅ repo  (todos los subscopes de repo)');
log('                  ✅ workflow  (opcional)');
log('  5) Generate token → copia el token (empieza con ghp_…)');
log('');

// Preguntar interactivamente (stdin)
async function ask() {
  return new Promise((res) => {
    process.stdout.write('Pega aquí el token (o Enter para salir): ');
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.resume();
    process.stdin.on('data', (chunk) => {
      data += chunk;
      if (data.includes('\n')) {
        process.stdin.pause();
        res(data.trim());
      }
    });
    process.stdin.on('end', () => res(data.trim()));
  });
}

async function main() {
  if (existsSync(TOKEN_FILE)) {
    const t = readFileSync(TOKEN_FILE, 'utf8').trim();
    if (t && t.startsWith('ghp_')) {
      log(`Ya tienes un token guardado en:\n   ${TOKEN_FILE}`);
      log(`  (termina en …${t.slice(-4)}) — si quieres cambiarlo,`);
      log(`  borra el archivo y vuelve a ejecutar este script.`);
      return;
    }
  }
  const tok = await ask();
  if (!tok) { log('Cancelado (no escribiste nada).'); return; }
  if (!tok.startsWith('ghp_') && !tok.startsWith('github_pat_')) {
    log('⚠️  El token no parece válido (debería empezar con ghp_ o github_pat_).');
    log(`   Lo guardo de todas formas, pero revisa. Path: ${TOKEN_FILE}`);
  }
  const dir = dirname(TOKEN_FILE);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  writeFileSync(TOKEN_FILE, tok, { mode: 0o600 });
  log(`✔ Token guardado en: ${TOKEN_FILE} (no va a git)`);
  log('');
  log('Para usarlo automáticamente, exporta la variable antes del release,');
  log('o el script release.mjs lo cargará solo. Ejemplo de uso:');
  log('   npm run release:patch');
}

// El release.mjs también carga este archivo si no hay GH_TOKEN en env:
// (lo inyecta aquí abajo)
if (!process.env.GH_TOKEN && !process.env.GITHUB_TOKEN && existsSync(TOKEN_FILE)) {
  // nothing — release.mjs lo lee
}

main().catch((e) => { console.error(e); process.exit(1); });
