import React, { useMemo, useState } from 'react'
import { Layout, Menu, ConfigProvider, Dropdown, Button, Modal, Form, Input, InputNumber, message, Card, Tabs, Space, Tag, Divider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { SettingOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
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
    // 从URL读取初始状态
    const getInitialState = () => {
        const hash = window.location.hash.slice(1) // 移除 #
        if (hash.startsWith('/run/')) {
            const rel = decodeURIComponent(hash.slice(5)) // 移除 '/run/'
            return { page: 'run' as Page, rel }
        }
        return { page: 'dashboard' as Page, rel: '' }
    }

    const [page, setPage] = useState<Page>(getInitialState().page)
    const [rel, setRel] = useState<string>(getInitialState().rel)

    // 监听URL变化
    React.useEffect(() => {
        const handleHashChange = () => {
            const state = getInitialState()
            setPage(state.page)
            setRel(state.rel)
        }

        window.addEventListener('hashchange', handleHashChange)
        return () => window.removeEventListener('hashchange', handleHashChange)
    }, [])

    // 初始化URL（如果没有hash则设置为dashboard）
    React.useEffect(() => {
        if (!window.location.hash) {
            window.location.hash = '#/dashboard'
        }
    }, [])

    // 更新URL的辅助函数
    const updateURL = (newPage: Page, newRel?: string) => {
        if (newPage === 'dashboard') {
            window.location.hash = '#/dashboard'
        } else if (newPage === 'run' && newRel) {
            window.location.hash = `#/run/${encodeURIComponent(newRel)}`
        }
    }

    // 菜单状态
    const [configModalVisible, setConfigModalVisible] = useState(false)
    const [promptForm] = Form.useForm()
    const [thresholdForm] = Form.useForm()
    const [promptConfig, setPromptConfig] = useState<{
        system_prompt: string
        parsed_config: Record<string, string>
        structured_config: Array<{ key: string, label: string, value: string, type: 'text' | 'number' | 'textarea' }>
    }>({ system_prompt: '', parsed_config: {}, structured_config: [] })

    // 启用滚动位置恢复
    useScrollRestore()

    // 解析提示词为结构化配置项
    const parsePromptToStructure = (prompt: string) => {
        const structuredConfig = [
            {
                key: 'role',
                label: '角色定义',
                value: extractValue(prompt, /你是一名(.+?)。/, '内核 UB 测试分析专家'),
                type: 'text' as const
            },
            {
                key: 'task',
                label: '主要任务',
                value: extractValue(prompt, /任务：(.+?)(?=\n准则：|\n\n)/s, '识别"真正异常"的指标，并给出最可能的根因'),
                type: 'textarea' as const
            },
            {
                key: 'robust_z_threshold',
                label: 'Robust Z-Score 阈值',
                value: extractValue(prompt, /abs\(robust_z\)≥(\d+(?:\.\d+)?)/),
                type: 'number' as const
            },
            {
                key: 'median_threshold',
                label: '中位数变化阈值(%)',
                value: extractValue(prompt, /Δ vs median.≥(\d+(?:\.\d+)?)%/),
                type: 'number' as const
            },
            {
                key: 'mean_threshold',
                label: '均值变化阈值(%)',
                value: extractValue(prompt, /Δ vs mean.≥(\d+(?:\.\d+)?)%/),
                type: 'number' as const
            },
            {
                key: 'platform',
                label: '目标平台',
                value: extractValue(prompt, /目标平台为\s*([^，,。\n]+)/, 'ARM64'),
                type: 'text' as const
            },
            {
                key: 'environment',
                label: '系统环境',
                value: extractValue(prompt, /Linux\s*([^。，,\n]+)/, 'Linux 内核 pKVM 场景（EL1/EL2）'),
                type: 'text' as const
            },
            {
                key: 'common_factors',
                label: '常见影响因素',
                value: extractValue(prompt, /常见影响因素包括：([^。]+)/, 'CPU 频率、热限频、调度失衡、中断亲和等'),
                type: 'textarea' as const
            },
            {
                key: 'language',
                label: '输出语言',
                value: extractValue(prompt, /所有自然语言字段请使用(.+?)表达/, '中文'),
                type: 'text' as const
            },
            {
                key: 'confidence_requirement',
                label: '置信度要求',
                value: extractValue(prompt, /置信度：(.+?)(?=\n-|\n\n|$)/, '每个异常项必须包含 confidence 字段（0~1之间的数值），不可为null或省略'),
                type: 'textarea' as const
            },
            {
                key: 'output_format',
                label: '输出格式',
                value: extractValue(prompt, /输出：(.+?)(?=；|$)/, 'confidence 返回 0~1 的小数；严格按 JSON 输出'),
                type: 'textarea' as const
            }
        ]

        return structuredConfig
    }

    // 辅助函数：从文本中提取值
    const extractValue = (text: string, pattern: RegExp, defaultValue: string = ''): string => {
        const match = text.match(pattern)
        return match ? match[1].trim() : defaultValue
    }

    // 从结构化配置重建提示词
    const rebuildPromptFromStructure = (structuredConfig: Array<{ key: string, value: string }>): string => {
        const configMap = structuredConfig.reduce((acc, item) => {
            acc[item.key] = item.value
            return acc
        }, {} as Record<string, string>)

        return `你是一名${configMap.role || '内核 UB 测试分析专家'}。你将收到当前 run 的各指标条目，以及每个指标的简短历史与统计特征。
任务：${configMap.task || '识别"真正异常"的指标，并给出最可能的根因（需结合统计特征进行证据化解释）'}。
准则：
- 波动性：UB 数据存在天然波动，请优先依据稳健统计特征（robust_z、与历史中位数/均值的百分比变化、history_n）。
- 阈值建议：abs(robust_z)≥${configMap.robust_z_threshold || '3'} 或 |Δ vs median|≥${configMap.median_threshold || '30'}% 或 |Δ vs mean|≥${configMap.mean_threshold || '30'}% 时可以判为异常；边界情况应谨慎，证据不足时判为非异常。
- 方向性：明确说明异常是"性能下降"还是"性能提升"，并用当前值与历史对比定量描述。
- 根因与证据：每个异常必须给出 primary_reason 与至少一个 root_cause（含 likelihood 0~1），并在 supporting_evidence 中引用具体特征（如历史样本数、robust_z、Δ% 等）。
- 置信度：${configMap.confidence_requirement || '每个异常项必须包含 confidence 字段（0~1之间的数值），不可为null或省略，基于统计证据强度评估'}。
- 环境：目标平台为 ${configMap.platform || 'ARM64'}，${configMap.environment || 'Linux 内核 pKVM 场景（EL1/EL2）'}。常见影响因素包括：${configMap.common_factors || 'CPU 频率/能效策略、热限频、big.LITTLE 调度失衡、中断亲和与 IRQ 绑核、cgroup/cpuset/rt 限制、虚拟化开销等'}。
- 术语边界：请避免输出 x86 专有概念（如 SMT/Turbo Boost 等），优先给出 ARM64/pKVM 相关表述。
- 语言：除专有名词外，所有自然语言字段请使用${configMap.language || '中文'}表达（含 primary_reason、root_causes.cause、suggested_next_checks 等）。
- ${configMap.output_format || '输出：confidence 返回 0~1 的小数；严格按 JSON 输出，符合给定 schema，不要输出 Markdown 或解释文字'}。`
    }

    // 菜单处理函数
    const openConfigModal = async () => {
        try {
            const [promptData, thresholdData] = await Promise.all([
                getJSON<{ system_prompt: string }>('/api/v1/config/prompt'),
                getJSON<{
                    robust_z_threshold: number
                    pct_change_threshold: number
                    metrics_info: Array<{ name: string, unit: string, description: string }>
                }>('/api/v1/config/thresholds')
            ])

            const structuredConfig = parsePromptToStructure(promptData.system_prompt)
            setPromptConfig({
                system_prompt: promptData.system_prompt,
                parsed_config: {},
                structured_config: structuredConfig
            })

            // 设置表单值
            const formValues: Record<string, any> = { system_prompt: promptData.system_prompt }
            structuredConfig.forEach(item => {
                formValues[item.key] = item.value
            })

            promptForm.setFieldsValue(formValues)
            thresholdForm.setFieldsValue({
                robust_z_threshold: thresholdData.robust_z_threshold,
                pct_change_threshold: thresholdData.pct_change_threshold
            })
            setConfigModalVisible(true)
        } catch (e) {
            message.error('获取配置失败: ' + String(e))
        }
    }

    const saveConfig = async () => {
        try {
            const promptValues = await promptForm.validateFields()
            const thresholdValues = await thresholdForm.validateFields()

            // 从表单值构建结构化配置
            const updatedStructuredConfig = promptConfig.structured_config.map(item => ({
                key: item.key,
                value: promptValues[item.key] || item.value
            }))

            // 构建更新后的提示词
            const updatedPrompt = rebuildPromptFromStructure(updatedStructuredConfig)

            await Promise.all([
                postJSON('/api/v1/config/prompt', { system_prompt: updatedPrompt }),
                postJSON('/api/v1/config/thresholds', thresholdValues)
            ])

            message.success('配置已更新')
            setConfigModalVisible(false)
        } catch (e) {
            message.error('保存配置失败: ' + String(e))
        }
    }

    const menuItems = [
        { key: 'config', label: '系统配置', onClick: openConfigModal }
    ]

    const content = useMemo(() => {
        if (page === 'dashboard') return <Dashboard onOpenRun={(r) => {
            setRel(r);
            setPage('run');
            updateURL('run', r);
        }} />
        return <RunDetail rel={rel} onBack={() => {
            setPage('dashboard');
            updateURL('dashboard');
        }} />
    }, [page, rel])

    return (
        <ConfigProvider
            theme={{ token: { colorPrimary: '#1677ff' } }}
            locale={zhCN}
        >
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

                {/* 系统配置模态框 */}
                <Modal
                    title="系统配置"
                    open={configModalVisible}
                    onCancel={() => setConfigModalVisible(false)}
                    onOk={saveConfig}
                    width={900}
                    style={{ top: 20 }}
                >
                    <Tabs
                        items={[
                            {
                                key: 'prompt',
                                label: '提示词配置',
                                children: (
                                    <Form form={promptForm} layout="vertical">
                                        <div style={{ marginBottom: 16 }}>
                                            <div style={{ marginBottom: 12 }}>
                                                <span style={{ fontWeight: 600 }}>结构化配置</span>
                                            </div>
                                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
                                                {promptConfig.structured_config.map((item) => (
                                                    <Card key={item.key} size="small" style={{ border: '1px solid #f0f0f0' }}>
                                                        <Form.Item
                                                            name={item.key}
                                                            label={item.label}
                                                            style={{ marginBottom: 0 }}
                                                        >
                                                            {item.type === 'textarea' ? (
                                                                <Input.TextArea
                                                                    rows={3}
                                                                    placeholder={`请输入${item.label}...`}
                                                                    style={{ fontSize: '12px' }}
                                                                />
                                                            ) : item.type === 'number' ? (
                                                                <InputNumber
                                                                    style={{ width: '100%' }}
                                                                    placeholder={`请输入${item.label}...`}
                                                                />
                                                            ) : (
                                                                <Input
                                                                    placeholder={`请输入${item.label}...`}
                                                                    style={{ fontSize: '12px' }}
                                                                />
                                                            )}
                                                        </Form.Item>
                                                    </Card>
                                                ))}
                                            </div>
                                        </div>

                                        <Divider />

                                        <div>
                                            <div style={{ marginBottom: 12 }}>
                                                <span style={{ fontWeight: 600 }}>完整提示词预览</span>
                                            </div>
                                            <Form.Item
                                                name="system_prompt"
                                                style={{ marginBottom: 0 }}
                                            >
                                                <Input.TextArea
                                                    rows={8}
                                                    placeholder="系统提示词的完整内容..."
                                                    style={{ fontFamily: 'monospace', fontSize: '11px', backgroundColor: '#fafafa' }}
                                                    disabled
                                                />
                                            </Form.Item>
                                            <div style={{ color: '#666', fontSize: '12px', marginTop: 8 }}>
                                                💡 提示词会根据上方结构化配置自动生成，如需手动编辑请联系管理员
                                            </div>
                                        </div>
                                    </Form>
                                )
                            },
                            {
                                key: 'thresholds',
                                label: '检测阈值',
                                children: (
                                    <Form form={thresholdForm} layout="vertical">
                                        <Card title="异常检测阈值" size="small">
                                            <div style={{ display: 'flex', gap: 24 }}>
                                                <Form.Item
                                                    name="robust_z_threshold"
                                                    label="Robust Z-Score 阈值"
                                                    rules={[{ required: true, message: '请输入阈值' }]}
                                                    style={{ flex: 1 }}
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
                                                <Form.Item
                                                    name="pct_change_threshold"
                                                    label="百分比变化阈值"
                                                    rules={[{ required: true, message: '请输入阈值' }]}
                                                    style={{ flex: 1 }}
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
                                            </div>
                                            <div style={{ color: '#666', fontSize: '12px', marginBottom: 16 }}>
                                                <Tag color="blue">建议</Tag>
                                                Robust Z-Score: 2.0-5.0，百分比变化: 0.10-0.50，值越小检测越敏感
                                            </div>
                                        </Card>

                                        <Card title="测试指标说明" size="small" style={{ marginTop: 16 }}>
                                            <div style={{ fontSize: '12px', color: '#666' }}>
                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px' }}>
                                                    <div><Tag size="small">综合评分</Tag> System Benchmarks Index Score</div>
                                                    <div><Tag size="small">整数运算</Tag> Dhrystone 2 (lps)</div>
                                                    <div><Tag size="small">浮点运算</Tag> Double-Precision Whetstone (MWIPS)</div>
                                                    <div><Tag size="small">I/O性能</Tag> File Copy (KBps)</div>
                                                    <div><Tag size="small">进程创建</Tag> Process Creation (lps)</div>
                                                    <div><Tag size="small">系统调用</Tag> System Call Overhead (lps)</div>
                                                </div>
                                            </div>
                                        </Card>
                                    </Form>
                                )
                            }
                        ]}
                    />
                    <Divider />
                    <div style={{ color: '#999', fontSize: '11px', textAlign: 'center' }}>
                        ⚠️ 配置修改仅在当前运行时生效，重启服务后会重置为默认值
                    </div>
                </Modal>
            </Layout>
        </ConfigProvider>
    )
}


