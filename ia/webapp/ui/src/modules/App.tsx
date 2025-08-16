import React, { useMemo, useState } from 'react'
import { Layout, Menu, ConfigProvider, Dropdown, Button, Modal, Form, Input, InputNumber, message, Card } from 'antd'
import { SettingOutlined } from '@ant-design/icons'
import { Dashboard } from './Dashboard'
import { RunDetail } from './RunDetail'
import { useScrollRestore } from '../hooks/useScrollRestore'

type Page = 'dashboard' | 'run'

async function getJSON<T>(url: string): Promise<T> {
    const r = await fetch(url)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json()
}

async function postJSON<T>(url: string, data: any): Promise<T> {
    const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(err.error || `HTTP ${r.status}`)
    }
    return r.json()
}

export function App() {
    const [page, setPage] = useState<Page>('dashboard')
    const [rel, setRel] = useState<string>('')

    // 菜单状态
    const [promptModalVisible, setPromptModalVisible] = useState(false)
    const [thresholdModalVisible, setThresholdModalVisible] = useState(false)
    const [promptForm] = Form.useForm()
    const [thresholdForm] = Form.useForm()

    // 启用滚动位置恢复
    useScrollRestore()

    // 菜单处理函数
    const openPromptModal = async () => {
        try {
            const data = await getJSON<{ system_prompt: string }>('/api/v1/config/prompt')
            promptForm.setFieldsValue({ system_prompt: data.system_prompt })
            setPromptModalVisible(true)
        } catch (e) {
            message.error('获取提示词失败: ' + String(e))
        }
    }

    const openThresholdModal = async () => {
        try {
            const data = await getJSON<{
                robust_z_threshold: number
                pct_change_threshold: number
                metrics_info: Array<{ name: string, unit: string, description: string }>
            }>('/api/v1/config/thresholds')
            thresholdForm.setFieldsValue({
                robust_z_threshold: data.robust_z_threshold,
                pct_change_threshold: data.pct_change_threshold
            })
            setThresholdModalVisible(true)
        } catch (e) {
            message.error('获取阈值配置失败: ' + String(e))
        }
    }

    const savePrompt = async (values: { system_prompt: string }) => {
        try {
            await postJSON('/api/v1/config/prompt', values)
            message.success('提示词已更新')
            setPromptModalVisible(false)
        } catch (e) {
            message.error('保存提示词失败: ' + String(e))
        }
    }

    const saveThresholds = async (values: { robust_z_threshold: number, pct_change_threshold: number }) => {
        try {
            await postJSON('/api/v1/config/thresholds', values)
            message.success('阈值配置已更新')
            setThresholdModalVisible(false)
        } catch (e) {
            message.error('保存阈值配置失败: ' + String(e))
        }
    }

    const menuItems = [
        { key: 'prompt', label: '提示词配置', onClick: openPromptModal },
        { key: 'thresholds', label: '阈值设置', onClick: openThresholdModal }
    ]

    const content = useMemo(() => {
        if (page === 'dashboard') return <Dashboard onOpenRun={(r) => { setRel(r); setPage('run') }} />
        return <RunDetail rel={rel} onBack={() => setPage('dashboard')} />
    }, [page, rel])

    return (
        <ConfigProvider theme={{ token: { colorPrimary: '#1677ff' } }}>
            <Layout style={{ minHeight: '100vh' }}>
                <Layout.Header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ color: '#fff', fontWeight: 600 }}>X Core 智能分析平台</div>
                    <Dropdown
                        menu={{ items: menuItems }}
                        placement="bottomRight"
                        trigger={['click']}
                    >
                        <Button type="text" icon={<SettingOutlined />} style={{ color: '#fff' }}>
                            配置
                        </Button>
                    </Dropdown>
                </Layout.Header>
                <Layout.Content style={{ padding: 16 }}>
                    {content}
                </Layout.Content>

                {/* 提示词配置模态框 */}
                <Modal
                    title="提示词配置"
                    open={promptModalVisible}
                    onCancel={() => setPromptModalVisible(false)}
                    onOk={() => promptForm.submit()}
                    width={800}
                >
                    <Form form={promptForm} layout="vertical" onFinish={savePrompt}>
                        <Form.Item
                            name="system_prompt"
                            label="系统提示词"
                            rules={[{ required: true, message: '请输入提示词' }]}
                        >
                            <Input.TextArea
                                rows={15}
                                placeholder="请输入 AI 分析时使用的系统提示词..."
                                style={{ fontFamily: 'monospace' }}
                            />
                        </Form.Item>
                        <div style={{ color: '#666', fontSize: '12px' }}>
                            注意：修改仅在当前运行时生效，重启服务后会重置为默认值。
                        </div>
                    </Form>
                </Modal>

                {/* 阈值配置模态框 */}
                <Modal
                    title="阈值设置"
                    open={thresholdModalVisible}
                    onCancel={() => setThresholdModalVisible(false)}
                    onOk={() => thresholdForm.submit()}
                    width={600}
                >
                    <Form form={thresholdForm} layout="vertical" onFinish={saveThresholds}>
                        <Form.Item
                            name="robust_z_threshold"
                            label="Robust Z-Score 阈值"
                            rules={[{ required: true, message: '请输入阈值' }]}
                        >
                            <InputNumber
                                min={0.1}
                                max={10}
                                step={0.1}
                                precision={1}
                                placeholder="如: 3.0"
                                style={{ width: '100%' }}
                            />
                        </Form.Item>
                        <div style={{ color: '#666', fontSize: '12px', marginBottom: 16 }}>
                            建议范围: 2.0-5.0，值越小检测越敏感
                        </div>

                        <Form.Item
                            name="pct_change_threshold"
                            label="百分比变化阈值"
                            rules={[{ required: true, message: '请输入阈值' }]}
                        >
                            <InputNumber
                                min={0.01}
                                max={1}
                                step={0.01}
                                precision={2}
                                placeholder="如: 0.30"
                                style={{ width: '100%' }}
                            />
                        </Form.Item>
                        <div style={{ color: '#666', fontSize: '12px', marginBottom: 16 }}>
                            建议范围: 0.10-0.50（即10%-50%），值越小检测越敏感
                        </div>

                        <Card title="主要测试指标说明" size="small">
                            <ul style={{ fontSize: '12px', color: '#666', paddingLeft: 16 }}>
                                <li><strong>System Benchmarks Index Score:</strong> UnixBench综合评分</li>
                                <li><strong>Dhrystone 2:</strong> CPU整数运算性能 (lps)</li>
                                <li><strong>Double-Precision Whetstone:</strong> CPU浮点运算性能 (MWIPS)</li>
                                <li><strong>File Copy:</strong> 文件系统I/O性能 (KBps)</li>
                                <li><strong>Process Creation:</strong> 进程创建性能 (lps)</li>
                                <li><strong>System Call Overhead:</strong> 系统调用开销 (lps)</li>
                            </ul>
                        </Card>

                        <div style={{ color: '#666', fontSize: '12px', marginTop: 16 }}>
                            注意：修改仅在当前运行时生效，重启服务后会重置为默认值。
                        </div>
                    </Form>
                </Modal>
            </Layout>
        </ConfigProvider>
    )
}


