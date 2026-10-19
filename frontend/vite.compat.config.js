const apiProxyTarget = process.env.VITE_API_PROXY || 'http://127.0.0.1:8000'

export default {
  esbuild: {
    jsxInject: "import React from 'react'",
  },
  server: {
    proxy: {
      '/api': apiProxyTarget,
    },
  },
}
