import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: fileURLToPath(new URL('../static/login', import.meta.url)),
    emptyOutDir: false,
    lib: { entry: fileURLToPath(new URL('./src/main.js', import.meta.url)), formats: ['es'], fileName: () => 'login.js' },
    cssCodeSplit: false,
    rollupOptions: { output: { assetFileNames: 'login.[ext]' } },
  },
})
