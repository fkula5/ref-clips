import { defineConfig } from 'vite'
import type { ProxyOptions } from 'vite'
import vue from '@vitejs/plugin-vue'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'

const target = process.env.FRONTEND_API_TARGET || 'http://127.0.0.1:8000'
const legacyPaths = [
  '/api', '/matches', '/clips', '/groups', '/sets', '/admin', '/static',
  '/login', '/logout', '/forgot-password', '/set-password', '/videos',
  '/uploads', '/notifications', '/settings', '/referees', '/sheets',
  '/self-assessments', '/scoresheets', '/watch', '/share-links', '/s/',
  '/unsubscribe/',
]
const proxy: Record<string, ProxyOptions> = Object.fromEntries(
  legacyPaths.map(path => [path, { target, changeOrigin: false }]),
)
proxy['/ws'] = { target, ws: true }
const proxiedBrowserPages = [
  /^\/matches(?:\/new|\/\d+(?:\/(?:edit|describe))?)?$/,
  /^\/clips(?:\/\d+)?$/,
  /^\/groups(?:\/\d+(?:\/review)?)?$/,
  /^\/notifications(?:\/settings)?$/,
  /^\/admin(?:\/[a-z-]+)?$/,
  /^\/sheets\/\d+(?:\/edit)?$/,
  /^\/self-assessments(?:\/\d+(?:\/edit)?)?$/,
  /^\/referees\/\d+$/,
  /^\/(?:s|set-password|unsubscribe)\/[A-Za-z0-9_-]+$/,
]

for (const prefix of [
  '/matches', '/clips', '/groups', '/notifications', '/admin', '/sheets', '/self-assessments',
  '/referees', '/s/', '/set-password', '/unsubscribe/',
]) {
  proxy[prefix].bypass = (request, response) => {
    if ((request.method !== 'GET' && request.method !== 'HEAD') ||
        !request.headers.accept?.includes('text/html') || request.headers['hx-request']) return
    const url = new URL(request.url ?? '/', 'http://localhost')
    const path = url.pathname.replace(/\/+$/, '')
    if (url.searchParams.get('view') !== 'classic' && proxiedBrowserPages.some(pattern => pattern.test(path))) {
      response?.setHeader('Cache-Control', 'no-store')
      response?.setHeader('Referrer-Policy', 'no-referrer')
      response?.setHeader('X-Robots-Tag', 'noindex, nofollow')
      return '/index.html'
    }
  }
}

export default defineConfig({
  plugins: [
    vue({ template: { transformAssetUrls, compilerOptions: {
      isCustomElement: tag => tag === 'video-player' || tag === 'video-neutral-skin',
    } } }),
    quasar(),
  ],
  server: { port: 5173, strictPort: true, proxy },
})
