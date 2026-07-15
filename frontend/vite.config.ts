import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'

export default defineConfig({
  plugins: [vue(), vueJsx()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8090',
        changeOrigin: true,
        // SSE 流式问答经此代理会被 Nagle 算法攒批：直连后端时逐字到达（同一份长回答
        // 分散在 130+ 个到达时间点），经这层代理后 50%+ 的内容会挤在最后 0.2s 一次性
        // 吐出，前端体感就是"一股脑蹦出来"。显式在两跳的 socket 上关闭 Nagle
        // （TCP_NODELAY），恢复逐块转发。仅影响本地 dev server，不影响生产部署
        // （生产环境前端走 Nginx/CDN 直接反代后端，没有这层 Node 代理）。
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setNoDelay?.(true)
          })
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            res.socket?.setNoDelay(true)
          })
        }
      }
    }
  }
})
