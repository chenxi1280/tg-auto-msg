import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],

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
        manualChunks: {
          'element-plus': ['element-plus'],
          'vue-vendor': ['vue', 'vue-router', 'pinia']
        }
      }
    }
  }
})
