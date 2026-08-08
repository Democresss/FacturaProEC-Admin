import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  base: './',                       // CRÍTICO para Electron: rutas relativas
                                    // (sin esto, index.html carga /assets/... y NO
                                    //  funciona con loadFile + protocolo file://)
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src/renderer'),
    },
  },
  root: 'src/renderer',           // index.html vive en src/renderer/
  build: {
    outDir: '../../dist/renderer', // salida a admin-electron/dist/renderer
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 3000,
    strictPort: true,
  },
});
