import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/config': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    // ECharts is ~744KB minified - this is expected for a full-featured charting library
    // It's lazy-loaded so it won't affect initial page load
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        // Function form (not object form). Vite 8 swapped Rollup for
        // Rolldown, which rejects the object-form `manualChunks`:
        //   error during build:
        //   [rolldown] Object form of `manualChunks` is not supported.
        // Function form works under both Rollup (vite 7) and Rolldown
        // (vite 8), so this is forward-compatible without gating on the
        // vite-version bump (PR #79). Match more-specific package names
        // BEFORE 'vue' because 'vue' is a substring of 'vue-echarts'
        // and '@iconify/vue'; path-segment matching (`/vue/`, `/pinia/`)
        // prevents the false-positive grouping that a bare substring
        // match would otherwise produce.
        manualChunks: (id) => {
          if (!id.includes('node_modules')) return
          if (id.includes('echarts') || id.includes('vue-echarts')) return 'echarts'
          if (id.includes('lucide-vue-next') || id.includes('@iconify/vue')) return 'icons'
          if (id.includes('axios')) return 'axios'
          if (id.includes('/vue/') || id.includes('/pinia/')) return 'vue-vendor'
        }
      }
    }
  }
})
