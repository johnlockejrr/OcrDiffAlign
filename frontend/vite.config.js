import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

const apiOrigin = process.env.OCRDIFF_API_ORIGIN ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api': { target: apiOrigin, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
});
