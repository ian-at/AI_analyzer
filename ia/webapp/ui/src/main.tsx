import React from 'react'
import 'antd/dist/reset.css'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App } from './modules/App'

const qc = new QueryClient({
    defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } }
})

createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <QueryClientProvider client={qc}>
            <App />
        </QueryClientProvider>
    </React.StrictMode>
)


