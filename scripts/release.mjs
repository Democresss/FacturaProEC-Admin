#!/usr/bin/env node
/* ──────────────────────────────────────────────────────────────────
 *  FacturaProEC Admin — Release automatizado
 *  ──────────────────────────────────────────────────────────────────
 *  Uso:
 *    npm run release:patch       # 2.0.0 → 2.0.1   (bug fixes)
 *    npm run release:minor        # 2.0.0 → 2.1.0   (nuevas features)
 *    npm run release:major        # 2.0.0 → 3.0.0   (breaking changes)
 *    npm run release              # sin bump (regenera el instalador)
 *
 *  Qué hace (en orden):
 *    1. Lee la versión actual de package.json
 *    2. Bump (patch/minor/major) y la guarda
 *    3. Compila main + renderer   (npm run build)
 *    4. Empaqueta Windows NSIS x64  (electron-builder)
 *    5. Arregla dist-build/latest.yml  → que el auto-updater use
 *       el NSIS x64 (no el portable) como archivo principal
 *    6. Hace git commit + git tag vX.Y.Z  (sólo código, sin binarios)
 *    7. Si existe GH_TOKEN  → sube todo al GitHub Release automáticamente
 *       Si no → imprime las instrucciones manuales (código + release web)
 *
 *  Resultado: las instalaciones anteriores detectan la nueva versión
 *  solas, la descargan y se actualizan al reiniciar.
 * ────────────────────────────────────────────────────────────────── */

import { execSync, spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync, copyFileSync, mkdirSync, statSync } from 'node:fs';
import { dirname, resolve, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import * as https from 'node:https';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const PKG_PATH = resolve(ROOT, 'package.json');
const DIST_BUILD = resolve(ROOT, 'dist-build');

const log = (...m) => console.log('\x1b[36m[release]\x1b[0m', ...m);
const err = (...m) => console.error('\x1b[31m[release:ERROR]\x1b[0m', ...m);
const ok = (...m) => console.log('\x1b[32m[release:OK]\x1b[0m', ...m);

function run(cmd, { cwd = ROOT, stdio = 'inherit' } = {}) {
  log('$', cmd);
  spawnSync(cmd, { cwd, stdio, shell: true });
}

/* ─── 1. Leer versión y bump ─── */
function bumpVersion(kind) {
  const pkg = JSON.parse(readFileSync(PKG_PATH, 'utf8'));
  const cur = pkg.version;
  if (!kind) return { pkg, cur, next: cur, bumped: false };
  const [maj, min, pat] = cur.split('.').map(Number);
  let next;
  if (kind === 'patch') next = `${maj}.${min}.${pat + 1}`;
  else if (kind === 'minor') next = `${maj}.${min + 1}.0`;
  else if (kind === 'major') next = `${maj + 1}.0.0`;
  else throw new Error(`Bump desconocido: ${kind}. Usa patch|minor|major`);
  pkg.version = next;
  writeFileSync(PKG_PATH, JSON.stringify(pkg, null, 2) + '\n');
  return { pkg, cur, next, bumped: true };
}

/* ─── 2. Build (TS main + renderer Vite) ─── */
function build() {
  log('Compilando TypeScript (main + renderer)…');
  const r = spawnSync('npm.cmd', ['run', 'build'], { cwd: ROOT, stdio: 'inherit', shell: true });
  if (r.status !== 0) throw new Error('npm run build falló');
  ok('Build OK');
}

/* ─── 3. Empaquetar Windows NSIS x64 ─── */
function packageWin() {
  const v = readVersion();
  const outDir = `dist-build-${v}`;
  // Limpiar el output efímero si ya existe (sin tocar el dist-build bloqueado)
  if (existsSync(resolve(ROOT, outDir))) {
    spawnSync('rm', ['-rf', outDir], { cwd: ROOT, shell: true });
  }
  log(`Empaquetando Windows NSIS x64 en ${outDir}/ (puede tardar 2-5 min)…`);
  // --win nsis:x64 → sólo NSIS 64 bits (el auto-updater usa este canal)
  const r = spawnSync('npx.cmd', [
    'electron-builder', '--win', 'nsis', '--x64',
    `--config.directories.output=${outDir}`,
    '--config.extraMetadata.version=' + v
  ], { cwd: ROOT, stdio: 'inherit', shell: true });
  if (r.status !== 0) throw new Error('electron-builder falló (¿proceso bloqueando archivos? cierra apps/Explorador)');
  ok('Empaquetado OK en', outDir);
  return outDir;
}

function readVersion() {
  return JSON.parse(readFileSync(PKG_PATH, 'utf8')).version;
}

/* Directorio de salida del builder (efímero: dist-build-${version}) */
let BUILD_OUT = DIST_BUILD;

/* ─── 4. Arreglar latest.yml ───
 * electron-builder en modo multi-target genera un latest.yml cuyo
 * `path` apunta al primer archivo generado. Para auto-update limpio
 * queremos que el archivo primario sea el NSIS x64 (es el que se
 * instala vía NSIS y se actualiza incrementalmente con blockmap).
 */
function sha512(path) {
  const buf = readFileSync(path);
  return createHash('sha512').update(buf).digest('base64');
}
function fileSize(path) {
  return statSync(path).size;
}

function fixLatestYml(version) {
  const ymlPath = resolve(BUILD_OUT, 'latest.yml');
  if (!existsSync(ymlPath)) { err('No se encontró latest.yml — ¿falló el builder?'); return; }

  const nsisX64 = `FacturaProEC-Admin-${version}-win-x64.exe`;
  const nsisX64Path = resolve(BUILD_OUT, nsisX64);
  if (!existsSync(nsisX64Path)) { err('No se encontró el NSIS x64:', nsisX64); return; }

  // Recopilar todos los .exe generados
  const files = [];
  for (const f of [
    `FacturaProEC-Admin-${version}-win-x64.exe`,
    `FacturaProEC-Admin-${version}-win-ia32.exe`,
  ]) {
    const p = resolve(BUILD_OUT, f);
    if (existsSync(p)) files.push({ url: f, sha512: sha512(p), size: fileSize(p) });
  }

  const primary = files.find(f => f.url.includes('win-x64')) || files[0];
  const lines = [
    `version: ${version}`,
    `files:`,
    ...files.map(f => `  - url: ${f.url}\n    sha512: ${f.sha512}\n    size: ${f.size}`),
    `path: ${primary.url}`,
    `sha512: ${primary.sha512}`,
    `releaseDate: '${new Date().toISOString()}'`,
  ];
  writeFileSync(ymlPath, lines.join('\n') + '\n');
  ok(`latest.yml corregido → NSIS x64 como primario (${primary.url})`);
}

/* ─── 5. Copiar instalador a Downloads ─── */
function copyToDownloads(version) {
  const exe = `FacturaProEC-Admin-${version}-win-x64.exe`;
  const src = resolve(BUILD_OUT, exe);
  const home = process.env.USERPROFILE || process.env.HOME;
  const dlDir = resolve(home, 'Downloads');
  if (!existsSync(dlDir)) mkdirSync(dlDir, { recursive: true });
  const dst = resolve(dlDir, exe);
  if (existsSync(src)) {
    copyFileSync(src, dst);
    ok(`Instalador copiado a:\n   ${dst}`);
  }
}

/* ─── 6. Git commit + tag (sólo código, sin binarios) ─── */
function gitCommitAndTag(version, bumped) {
  // No commitear si no hay cambios reales de código más allá del bump
  const status = execSync('git status --porcelain', { cwd: ROOT }).toString().trim();
  if (!status) { log('Sin cambios en el árbol de git (nada que commitear).'); return false; }

  // Asegurar que sólo código va al commit (el .gitignore ya excluye binarios)
  spawnSync('git', ['add', '-A'], { cwd: ROOT, stdio: 'inherit' });
  const msg = bumped ? `v${version}` : `chore: regenera instalador v${version}`;
  const tag = `v${version}`;
  const r = spawnSync('git', ['commit', '-m', msg], { cwd: ROOT, stdio: 'inherit' });
  if (r.status !== 0) { err('git commit falló — arréglalo a mano'); return false; }

  // Tag (si ya existe, lo salteamos)
  const tagExists = spawnSync('git', ['rev-parse', tag], { cwd: ROOT }).status === 0;
  if (!tagExists) {
    spawnSync('git', ['tag', tag], { cwd: ROOT, stdio: 'inherit' });
    ok(`Tag creado: ${tag}`);
  }
  ok(`Commit hecho: ${msg}`);
  return true;
}

/* ─── 7a. Upload a GitHub Release con GH_TOKEN ─── */
function readStoredToken() {
  if (process.env.GH_TOKEN) return process.env.GH_TOKEN;
  if (process.env.GITHUB_TOKEN) return process.env.GITHUB_TOKEN;
  const home = process.env.USERPROFILE || process.env.HOME;
  const tf = resolve(home, '.facturaproec-gh-token');
  if (existsSync(tf)) return readFileSync(tf, 'utf8').trim();
  return null;
}
function uploadToGithub(version) {
  const token = readStoredToken();
  const repo = readRepoSlug();
  if (!token) {
    err('No hay GH_TOKEN — no se puede subir automáticamente.');
    log('   Ejecuta primero:  npm run gh:auth   (te guía para crear el token)');
    printManualReleaseInstructions(version, repo);
    return false;
  }
  // Usar el REST API de GitHub para: crear release + subir assets
  const tag = `v${version}`;
  const createBody = JSON.stringify({
    tag_name: tag,
    name: `FacturaProEC Admin v${version}`,
    body: `Auto-generado por \`npm run release\`.\n\nVer [commits para v${tag}](https://github.com/${repo}/releases/tag/${tag}).`,
    draft: false,
    prerelease: false,
  });
  const r = spawnSync('node', ['-e', `
    const https = require('https');
    const body = ${JSON.stringify(createBody)};
    const opts = { hostname:'api.github.com', path:'/repos/${repo}/releases', method:'POST',
      headers: { 'Authorization':'token ${token}', 'Accept':'application/vnd.github+json',
        'Content-Type':'application/json', 'Content-Length':Buffer.byteLength(body),
        'User-Agent':'facturaproec-release' } };
    https.request(opts, res=>{ let d=''; res.on('data',c=>d+=c); res.on('end',()=>{
      try{ const j=JSON.parse(d); console.log(res.statusCode, j.id||j.message);
        if(j.id) require('fs').writeFileSync('.release-id', String(j.id));
      }catch(e){ console.log(res.statusCode, d); }
    });}).end(body);
  `], { cwd: ROOT, stdio: 'inherit' });
  if (r.status !== 0 || !existsSync(resolve(ROOT, '.release-id'))) {
    err('No se pudo crear el release en GitHub (¿existe el repo? ¿permisos del token?).');
    printManualReleaseInstructions(version, repo);
    return false;
  }
  const releaseId = readFileSync(resolve(ROOT, '.release-id'), 'utf8').trim();

  // Subir assets: el NSIS x64 y el latest.yml
  const version_str = version;
  const assets = [
    `FacturaProEC-Admin-${version_str}-win-x64.exe`,
    `latest.yml`,
    `FacturaProEC-Admin-${version_str}-win-x64.exe.blockmap`,
  ];
  for (const a of assets) {
    const ap = resolve(BUILD_OUT, a);
    if (!existsSync(ap)) { log('Skipping (no existe):', a); continue; }
    uploadAsset(releaseId, ap, repo, token);
  }
  ok(`Release subido: https://github.com/${repo}/releases/tag/${tag}`);
  return true;
}

function uploadAsset(releaseId, filePath, repo, token) {
  const name = basename(filePath);
  const buf = readFileSync(filePath);
  // GitHub requiere POST a /repos/:owner/:repo/releases/:id/assets?name=
  // Usamos multipart binario via PUT directo con content-type application/octet-stream.
  const path = `/repos/${repo}/releases/${releaseId}/assets?name=${encodeURIComponent(name)}`;
  const r = spawnSync('node', ['-e', `
    const https=require('https'); const fs=require('fs');
    const buf=fs.readFileSync(${JSON.stringify(filePath.replace(/\\/g,'/'))});
    const opts={hostname:'uploads.github.com', path:${JSON.stringify(path)},
      method:'POST', headers:{'Authorization':'token ${token}','Accept':'application/vnd.github+json',
        'Content-Type':'application/octet-stream','Content-Length':buf.length,'User-Agent':'facturaproec-release'}};
    https.request(opts,res=>{let d='';res.on('data',c=>d+=c);res.on('end',()=>console.log('  ${name}',res.statusCode));}).end(buf);
  `], { cwd: ROOT, stdio: 'inherit' });
}

function readRepoSlug() {
  const pkg = JSON.parse(readFileSync(PKG_PATH, 'utf8'));
  const p = pkg.build?.publish;
  if (p?.provider === 'github' && p.owner && p.repo) return `${p.owner}/${p.repo}`;
  return null;
}

/* ─── 7b. Instrucciones manuales (sin token) ─── */
function printManualReleaseInstructions(version, repo) {
  console.log('\n════════════════════════════════════════════════════════════════');
  console.log('  📦 Release lista para subir a mano (5 min en el navegador)');
  console.log('════════════════════════════════════════════════════════════════');
  console.log(`Repo:    https://github.com/${repo}`);
  console.log(`Versión: v${version}`);
  console.log('');
  console.log('1) Sube el código (si usas GitHub Desktop o git push):');
  console.log('     git push origin main --tags');
  console.log('');
  console.log('2) Crea la release:');
  console.log(`   👉 https://github.com/${repo}/releases/new?tag=v${version}`);
  console.log('   Title: FacturaProEC Admin v' + version);
  console.log('');
  console.log('3) Adjunta estos archivos (de admin-electron/dist-build/):');
  const exes = [
    `FacturaProEC-Admin-${version}-win-x64.exe`,
    `FacturaProEC-Admin-${version}-win-x64.exe.blockmap`,
    `latest.yml`,
  ];
  console.log('   ' + exes.filter(f => existsSync(resolve(BUILD_OUT, f))).join('\n   '));
  console.log('');
  console.log('4) Marca "Set as the latest release" → Publish release');
  console.log('');
  console.log('A partir de ahí, las instalaciones viejas detectan esta release');
  console.log('automáticamente y se actualizan solas. ✅');
  console.log('════════════════════════════════════════════════════════════════\n');
}

/* ─── MAIN ─── */
const arg = process.argv[2];
const kind = ['patch','minor','major'].includes(arg) ? arg : null;

try {
  log(`Vamos a release ${kind ? ('(' + kind + ')') : '(sin bump)'}`);
  const { pkg, cur, next, bumped } = bumpVersion(kind);
  log(`Versión: ${cur} → ${next}`);

  build();
  BUILD_OUT = resolve(ROOT, packageWin());
  fixLatestYml(next);
  copyToDownloads(next);
  const committed = gitCommitAndTag(next, bumped);

  // Si hubo commit y hay remoto push, intentar el push
  if (committed) {
    const hasRemote = spawnSync('git', ['remote', 'get-url', 'origin'], { cwd: ROOT }).status === 0;
    if (hasRemote) {
      log('Pushing a origin main + tags…');
      spawnSync('git', ['push', 'origin', 'main', '--tags'], { cwd: ROOT, stdio: 'inherit' });
    } else {
      log('No hay remote "origin" configurado — saltando push. (ejecuta gh:auth primero)');
    }
  }

  // Upload a GitHub (si hay token) o instrucciones manuales
  const repo = readRepoSlug();
  if (repo) uploadToGithub(next);
  else err('No hay build.publish.github.repo en package.json — no puedo subir.');

  ok('RELEASE COMPLETA');
} catch (e) {
  err(e.message);
  console.error(e.stack);
  process.exit(1);
}
