const { defineConfig } = require('vite')
const react = require('@vitejs/plugin-react')

module.exports = defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/analyse':   { target: 'http://localhost:8000', changeOrigin: true },
      '/decisions': { target: 'http://localhost:8000', changeOrigin: true },
      '/sar':       { target: 'http://localhost:8000', changeOrigin: true },
      '/health':    { target: 'http://localhost:8000', changeOrigin: true },
      '/traces':    { target: 'http://localhost:8000', changeOrigin: true },
      '/stats':     { target: 'http://localhost:8000', changeOrigin: true },
      '/auth':      { target: 'http://localhost:8000', changeOrigin: true },
      '/gmail':     { target: 'http://localhost:8000', changeOrigin: true },
      '/feedback':  { target: 'http://localhost:8000', changeOrigin: true },
      '/learning':  { target: 'http://localhost:8000', changeOrigin: true },
    }
  },
  build: {
    outDir: '../agent/static',
    emptyOutDir: true,
  }
})
