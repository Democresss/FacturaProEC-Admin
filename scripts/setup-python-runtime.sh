#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
#  setup-python-runtime.sh
#  Prepara el runtime Python embebido dentro del .exe.
#  Ejecutar UNA vez antes del primer build que incluya el runtime:
#    bash scripts/setup-python-runtime.sh
#  Idempotente: si resources/python-runtime/python.exe ya existe, sale.
# ──────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")/.."

RT="resources/python-runtime"
PYVER="3.13.0"
URL="https://www.python.org/ftp/python/${PYVER}/python-${PYVER}-embed-amd64.zip"

mkdir -p "$RT"

# Idempotente: si ya está listo, salir
if [ -f "$RT/python.exe" ] && [ -d "$RT/Lib/site-packages" ] && [ -d "$RT/Lib/site-packages/fastapi" ]; then
  echo "[setup-py] Runtime listo en $RT/python.exe (nada que hacer)"
  exit 0
fi

echo "[setup-py] Descargando Python $PYVER embeddable x64…"
curl -L -o "$RT/python-embed.zip" "$URL"
echo "[setup-py] Descomprimiendo…"
unzip -q "$RT/python-embed.zip" -d "$RT"
rm "$RT/python-embed.zip"

# Habilitar site-packages en ._pth (por default viene desactivado)
cat > "$RT/python313._pth" <<'EOF'
python313.zip
.
Lib
Lib\site-packages
import site
EOF

echo "[setup-py] Instalando pip en el runtime…"
curl -sL -o "$RT/get-pip.py" https://bootstrap.pypa.io/get-pip.py
"$RT/python.exe" "$RT/get-pip.py" --no-warn-script-location
rm "$RT/get-pip.py"

echo "[setup-py] Instalando dependencias runtime (fastapi, sqlalchemy, asyncpg, paramiko…)…"
"$RT/python.exe" -m pip install --no-warn-script-location --disable-pip-version-check \
  "uvicorn[standard]>=0.24.0" \
  "fastapi>=0.104.0" \
  "pydantic>=2.5.0" \
  "sqlalchemy[asyncio]>=2.0.0" \
  "asyncpg>=0.29.0" \
  "psycopg2-binary>=2.9.9" \
  "aiosqlite>=0.19.0" \
  "paramiko>=3.4.0" \
  "requests>=2.31.0"

# Limpieza: basura que no necesitamos en el .exe
"$RT/python.exe" -m pip cache purge 2>/dev/null || true
find "$RT" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$RT" -name "*.pyc" -delete 2>/dev/null || true

echo "[setup-py] Verificando imports…"
"$RT/python.exe" -c "import fastapi, uvicorn, sqlalchemy, asyncpg, paramiko, requests, aiosqlite, pydantic, psycopg2; print('TODAS OK en runtime embebido')"

echo "[setup-py] Rtotal: $(du -sh "$RT" | cut -f1) en $RT"
echo "[setup-py] LISTO. Ahora corré: npm run release:patch"
