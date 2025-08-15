import React, { useMemo, useState } from 'react'
import { Layout, Menu, ConfigProvider } from 'antd'
import { Dashboard } from './Dashboard'
import { RunDetail } from './RunDetail'
import { useScrollRestore } from '../hooks/useScrollRestore'

type Page = 'dashboard' | 'run'

export function App() {
    const [page, setPage] = useState<Page>('dashboard')
    const [rel, setRel] = useState<string>('')

    // 启用滚动位置恢复
    useScrollRestore()

    const content = useMemo(() => {
        if (page === 'dashboard') return <Dashboard onOpenRun={(r) => { setRel(r); setPage('run') }} />
        return <RunDetail rel={rel} onBack={() => setPage('dashboard')} />
    }, [page, rel])

    return (
        <ConfigProvider theme={{ token: { colorPrimary: '#1677ff' } }}>
            <Layout style={{ minHeight: '100vh' }}>
                <Layout.Header>
                    <div style={{ color: '#fff', fontWeight: 600 }}>IA 控制台</div>
                </Layout.Header>
                <Layout.Content style={{ padding: 16 }}>
                    {content}
                </Layout.Content>
            </Layout>
        </ConfigProvider>
    )
}


