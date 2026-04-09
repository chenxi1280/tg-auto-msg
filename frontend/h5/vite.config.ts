import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      dts: 'src/auto-imports.d.ts',
      imports: ['vue', 'vue-router', 'pinia'],
      resolvers: [ElementPlusResolver()],
    }),
    Components({
      dts: 'src/components.d.ts',
      resolvers: [ElementPlusResolver({ importStyle: 'css' })],
    }),
  ],

  // 路径别名
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },

  // 开发服务器配置
  server: {
    port: 5173,
    host: true,
    // 代理配置：将 /api 请求代理到后端服务
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  },

  // 构建配置
  build: {
    // 输出目录
    outDir: 'dist',
    // 生成源码映射
    sourcemap: false,
    // 压缩配置
    minify: 'esbuild',
    // 分块策略
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('/node_modules/vue/') || id.includes('/node_modules/vue-router/') || id.includes('/node_modules/pinia/')) {
              return 'vue-vendor'
            }
            if (id.includes('/node_modules/axios/') || id.includes('/node_modules/jwt-decode/')) {
              return 'network-utils'
            }
            if (id.includes('/node_modules/qrcode/')) {
              return 'qrcode-utils'
            }
            return
          }
          if (id.includes('/src/utils/adminConsole')) {
            return 'admin-utils'
          }
        },
      }
    }
  }
})
