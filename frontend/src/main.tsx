import React from 'react'
import ReactDOM from 'react-dom/client'
// Self-hosted fonts (no CDN, no layout shift). Inter for UI text, JetBrains
// Mono for every number/id/code-like token.
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import App from './App'
import './index.css'

const root = document.getElementById('root')
if (root === null) throw new Error('Root element #root not found in index.html')

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
