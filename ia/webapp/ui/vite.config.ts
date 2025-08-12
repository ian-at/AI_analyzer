import { defineConfig } from 'vite'
import path from 'path'

// 构建输出到 ../static/ui
export default defineConfig({
    root: '.',
    base: '/static/ui/',
    build: {
        outDir: path.resolve(__dirname, '../static/ui'),
        emptyOutDir: true
    },
    server: {
        port: 5173,
        open: false
    }
})

