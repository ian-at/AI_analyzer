import React, { useMemo, useState } from 'react'
import { Card, Row, Col, Table, Tag, Space, Button, DatePicker, Select, Input, Switch, message, Modal, Form, InputNumber, Progress, Statistic, Alert, Spin, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined, ReloadOutlined, SearchOutlined, FileTextOutlined, DownloadOutlined, ThunderboltOutlined, LineChartOutlined, BarChartOutlined, PieChartOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

async function getJSON<T>(url: string): Promise<T> {
    const r = await fetch(url)
    if (!r.ok) throw new Error(String(r.status))
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

type InterfaceRunsResp = {
    runs: Array<{
        rel: string
        date: string
        patch_id?: string
        patch_set?: string
        total_tests?: number
        passed_tests?: number
        failed_tests?: number
        success_rate?: number
        analysis_time?: string
        has_analysis?: boolean
        downloaded_at?: string
    }>
    page: number
    page_size: number
    total: number
}

type InterfaceSummaryResp = {
    total_runs: number
    average_success_rate: number
    recent_trend: string
    analyzed_runs: number
}

type JobResp = {
    job_id: string
}

export function InterfaceTestDashboard(props: { onOpenRun: (rel: string) => void }) {
    // 状态管理（复用单元测试的状态结构）
    const [dateRange, setDateRange] = useState<[any, any] | null>(null)
    const [patchId, setPatchId] = useState<string>('')
    const [failedOnly, setFailedOnly] = useState<boolean>(false)
    const [page, setPage] = useState<number>(1)
    const [pageSize, setPageSize] = useState<number>(20)

    // 数据获取和分析状态
    const [showCrawlModal, setShowCrawlModal] = useState(false)
    const [showAnalysisModal, setShowAnalysisModal] = useState(false)
    const [crawlForm] = Form.useForm()
    const [analysisForm] = Form.useForm()
    const [currentJobId, setCurrentJobId] = useState<string | null>(null)
    const [singleAnalysisLoading, setSingleAnalysisLoading] = useState<string | null>(null)

    // 构建查询URL（适配接口测试）
    const runsUrl = useMemo(() => {
        const params = new URLSearchParams()
        params.set('page', String(page))
        params.set('page_size', String(pageSize))
        params.set('test_type', 'interface')

        if (failedOnly) params.set('failed_only', 'true')
        if (patchId && patchId.trim()) params.set('patch_id', patchId.trim())
        if (dateRange && dateRange[0] && dateRange[1]) {
            try {
                params.set('start', dateRange[0].format('YYYY-MM-DD'))
                params.set('end', dateRange[1].format('YYYY-MM-DD'))
            } catch (e) {
                console.warn('日期格式错误:', e)
            }
        }
        return `/api/v1/interface/runs?${params.toString()}`
    }, [page, pageSize, failedOnly, patchId, dateRange])

    // 数据查询
    const runs = useQuery<InterfaceRunsResp>({
        queryKey: ['interface-runs', runsUrl],
        queryFn: () => getJSON(runsUrl)
    })

    // 统计数据查询
    const summary = useQuery<InterfaceSummaryResp>({
        queryKey: ['interface-summary'],
        queryFn: () => getJSON<InterfaceSummaryResp>('/api/v1/interface/summary')
    })

    const pollJobStatus = (jobId: string, onComplete?: () => void) => {
        const interval = setInterval(async () => {
            try {
                const resp = await fetch(`/api/v1/jobs/${jobId}`)
                if (!resp.ok) throw new Error('查询任务状态失败')

                const data = await resp.json()
                if (data.status === 'completed') {
                    clearInterval(interval)
                    message.success('任务完成')
                    // 刷新数据
                    runs.refetch()
                    summary.refetch()
                    if (onComplete) onComplete()
                } else if (data.status === 'failed') {
                    clearInterval(interval)
                    message.error('任务失败: ' + (data.error || '未知错误'))
                    if (onComplete) onComplete()
                }
            } catch (error) {
                clearInterval(interval)
                message.error('查询任务状态失败')
                if (onComplete) onComplete()
            }
        }, 2000)

        // 5分钟后停止轮询
        setTimeout(() => clearInterval(interval), 5 * 60 * 1000)
    }

    // 数据获取
    const handleCrawl = async () => {
        try {
            const values = await crawlForm.validateFields()
            const data: JobResp = await postJSON('/api/v1/interface/crawl', {
                days: values.days || 7,
                patch_id: values.patch_id
            })

            setCurrentJobId(data.job_id)
            message.success('已开始获取接口测试数据')
            setShowCrawlModal(false)
            crawlForm.resetFields()

            // 轮询任务状态
            pollJobStatus(data.job_id)
        } catch (error) {
            message.error('获取数据失败: ' + String(error))
        }
    }

    // 批量分析
    const handleAnalysis = async () => {
        try {
            const values = await analysisForm.validateFields()
            const data: JobResp = await postJSON('/api/v1/interface/analyze', {
                days: values.days || 7,
                force: values.force || false
            })

            setCurrentJobId(data.job_id)
            message.success('已开始分析接口测试数据')
            setShowAnalysisModal(false)
            analysisForm.resetFields()

            // 轮询任务状态
            pollJobStatus(data.job_id)
        } catch (error) {
            message.error('分析失败: ' + String(error))
        }
    }

    // 单个运行分析
    const analyzeSingleRun = async (rel: string, forceReanalyze: boolean = false) => {
        try {
            setSingleAnalysisLoading(rel)

            // 根据是否强制重新分析选择不同的API端点
            const endpoint = forceReanalyze
                ? `/api/v1/interface/runs/${encodeURIComponent(rel)}/reanalyze`
                : `/api/v1/interface/runs/${encodeURIComponent(rel)}/analyze`

            const data: JobResp = await postJSON(endpoint, {})

            const actionText = forceReanalyze ? '重新分析' : '分析'
            message.success(`已开始${actionText}单个测试运行`)

            // 轮询任务状态
            pollJobStatus(data.job_id, () => {
                setSingleAnalysisLoading(null)
            })
        } catch (error) {
            message.error('分析失败: ' + String(error))
            setSingleAnalysisLoading(null)
        }
    }

    // 如果运行记录加载中，显示加载状态
    if (runs.isLoading) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
                <Spin size="large" tip="加载接口测试数据..." />
            </div>
        )
    }

    // 如果运行记录加载失败，显示错误信息
    if (runs.error) {
        return (
            <div style={{ padding: 24 }}>
                <Alert
                    message="加载失败"
                    description={String(runs.error)}
                    type="error"
                    showIcon
                    action={
                        <Button size="small" onClick={() => runs.refetch()}>
                            重试
                        </Button>
                    }
                />
            </div>
        )
    }

    // 表格列定义（复用单元测试的表格结构）
    const columns = [
        {
            title: '日期',
            dataIndex: 'downloaded_at',
            key: 'downloaded_at',
            width: 120,
            render: (date: string, record: any) => {
                // 优先使用downloaded_at，如果没有则使用date
                const displayDate = record.downloaded_at || record.date
                return dayjs(displayDate).format('YYYY-MM-DD HH:mm')
            }
        },
        {
            title: '补丁信息',
            key: 'patch',
            width: 150,
            render: (r: any) => (
                <Space size="small">
                    <Tag color="blue">P{r.patch_id || 'N/A'}</Tag>
                    <Tag>PS{r.patch_set || 'N/A'}</Tag>
                </Space>
            )
        },
        {
            title: '测试结果',
            key: 'result',
            width: 200,
            render: (r: any) => {
                const total = r.total_tests || 0
                const passed = r.passed_tests || 0
                const failed = r.failed_tests || 0
                const rate = r.success_rate || 0

                let status: 'success' | 'error' | 'warning'
                let icon: React.ReactNode

                if (rate === 100) {
                    status = 'success'
                    icon = <CheckCircleOutlined />
                } else if (rate >= 90) {
                    status = 'warning'
                    icon = <ExclamationCircleOutlined />
                } else {
                    status = 'error'
                    icon = <CloseCircleOutlined />
                }

                return (
                    <Space size="small">
                        <Tag color={status === 'success' ? 'green' : status === 'error' ? 'red' : 'orange'} icon={icon}>
                            {rate.toFixed(2)}%
                        </Tag>
                        <span style={{ fontSize: 12, color: '#666' }}>
                            {passed}/{total} 通过
                        </span>
                        {failed > 0 && (
                            <Tag color="red">{failed} 失败</Tag>
                        )}
                    </Space>
                )
            }
        },
        {
            title: '成功率',
            key: 'progress',
            width: 150,
            render: (r: any) => {
                const rate = r.success_rate || 0
                return (
                    <Progress
                        percent={rate}
                        size="small"
                        status={rate === 100 ? 'success' : rate < 90 ? 'exception' : 'normal'}
                        format={(percent) => `${percent?.toFixed(2)}%`}
                    />
                )
            }
        },
        {
            title: '分析状态',
            key: 'analysis',
            width: 100,
            render: (r: any) => {
                const analyzed = r.has_analysis || false
                const successRate = r.success_rate || 0

                // 如果成功率是100%，显示"-"
                if (successRate >= 100) {
                    return <span style={{ color: '#999' }}>-</span>
                }

                return analyzed ? (
                    <Tag color="green" icon={<CheckCircleOutlined />}>
                        已分析
                    </Tag>
                ) : (
                    <Tag color="default">未分析</Tag>
                )
            }
        },
        {
            title: '操作',
            key: 'actions',
            width: 180,
            fixed: 'right' as const,
            render: (r: any) => {
                const analyzed = r.has_analysis || false
                const label = analyzed ? '重新分析' : '分析'
                const successRate = r.success_rate || 0
                const showAnalyzeButton = successRate < 100

                return (
                    <Space size="small">
                        {showAnalyzeButton && (
                            <Button
                                size="small"
                                type={analyzed ? 'default' : 'primary'}
                                icon={<ThunderboltOutlined />}
                                onClick={() => analyzeSingleRun(r.rel, analyzed)}
                                loading={singleAnalysisLoading === r.rel}
                            >
                                {label}
                            </Button>
                        )}
                        <Button
                            type="link"
                            size="small"
                            icon={<FileTextOutlined />}
                            onClick={() => props.onOpenRun(r.rel)}
                        >
                            详情
                        </Button>
                    </Space>
                )
            }
        }
    ]

    return (
        <div style={{ padding: '16px' }}>

            {/* 统计卡片 */}
            <Row gutter={[16, 16]} style={{ marginBottom: '24px' }}>
                <Col span={6}>
                    <Card>
                        <Statistic
                            title="总运行次数"
                            value={summary.data?.total_runs || 0}
                            suffix="次"
                            prefix={<BarChartOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={6}>
                    <Card>
                        <Statistic
                            title="平均成功率"
                            value={summary.data?.average_success_rate || 0}
                            precision={2}
                            suffix="%"
                            valueStyle={{
                                color: (summary.data?.average_success_rate || 0) >= 95 ? '#3f8600' :
                                    (summary.data?.average_success_rate || 0) >= 90 ? '#faad14' : '#cf1322'
                            }}
                            prefix={<CheckCircleOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={6}>
                    <Card>
                        <Statistic
                            title="已分析记录"
                            value={summary.data?.analyzed_runs || 0}
                            suffix="个"
                            prefix={<LineChartOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={6}>
                    <Card>
                        <Statistic
                            title="质量趋势"
                            value={summary.data?.recent_trend === 'improving' ? '上升' :
                                summary.data?.recent_trend === 'declining' ? '下降' : '稳定'}
                            valueStyle={{
                                color: summary.data?.recent_trend === 'improving' ? '#3f8600' :
                                    summary.data?.recent_trend === 'declining' ? '#cf1322' : '#666'
                            }}
                            prefix={summary.data?.recent_trend === 'improving' ? '↑' :
                                summary.data?.recent_trend === 'declining' ? '↓' : '→'}
                        />
                    </Card>
                </Col>
            </Row>

            {/* 主要内容区 */}
            <Card
                title="接口测试运行记录"
                extra={
                    <Space>
                        <Button
                            type="primary"
                            icon={<DownloadOutlined />}
                            onClick={() => setShowCrawlModal(true)}
                        >
                            获取数据
                        </Button>
                        <Button
                            icon={<ThunderboltOutlined />}
                            onClick={() => setShowAnalysisModal(true)}
                        >
                            AI分析
                        </Button>
                        <Button
                            icon={<ReloadOutlined />}
                            onClick={() => {
                                runs.refetch()
                                summary.refetch()
                            }}
                            loading={runs.isFetching}
                        >
                            刷新
                        </Button>
                    </Space>
                }
            >
                {/* 筛选条件 */}
                <Row gutter={16} style={{ marginBottom: 16 }}>
                    <Col span={6}>
                        <DatePicker.RangePicker
                            value={dateRange}
                            onChange={setDateRange}
                            style={{ width: '100%' }}
                            placeholder={['开始日期', '结束日期']}
                        />
                    </Col>
                    <Col span={4}>
                        <Input
                            placeholder="补丁ID"
                            prefix={<SearchOutlined />}
                            value={patchId}
                            onChange={(e) => setPatchId(e.target.value)}
                            allowClear
                        />
                    </Col>
                    <Col span={4}>
                        <Switch
                            checked={failedOnly}
                            onChange={setFailedOnly}
                            checkedChildren="仅失败"
                            unCheckedChildren="全部"
                        />
                    </Col>
                </Row>

                {/* 数据表格 */}
                {runs.data?.runs && runs.data.runs.length > 0 ? (
                    <Table
                        columns={columns}
                        dataSource={runs.data.runs}
                        rowKey="rel"
                        loading={runs.isLoading}
                        pagination={{
                            current: page,
                            pageSize: pageSize,
                            total: runs.data?.total || 0,
                            onChange: (p, ps) => {
                                setPage(p)
                                setPageSize(ps || 20)
                            },
                            showSizeChanger: true,
                            showTotal: (total) => `共 ${total} 条记录`
                        }}
                        size="small"
                        scroll={{ x: 1000 }}
                    />
                ) : (
                    <Empty description="暂无数据" />
                )}
            </Card>

            {/* 获取数据对话框 */}
            <Modal
                title="获取接口测试数据"
                open={showCrawlModal}
                onCancel={() => setShowCrawlModal(false)}
                onOk={handleCrawl}
                okText="开始获取"
                cancelText="取消"
            >
                <Form
                    form={crawlForm}
                    layout="vertical"
                    initialValues={{ days: 7 }}
                >
                    <Form.Item
                        name="days"
                        label="获取最近天数"
                        rules={[{ required: true, message: '请输入天数' }]}
                    >
                        <InputNumber
                            min={1}
                            max={30}
                            style={{ width: '100%' }}
                            placeholder="请输入天数"
                        />
                    </Form.Item>
                    <Form.Item
                        name="patch_id"
                        label="补丁ID（可选）"
                    >
                        <Input placeholder="指定补丁ID，留空获取所有" />
                    </Form.Item>
                </Form>
            </Modal>

            {/* AI分析对话框 */}
            <Modal
                title="批量AI分析"
                open={showAnalysisModal}
                onCancel={() => setShowAnalysisModal(false)}
                onOk={handleAnalysis}
                okText="开始分析"
                cancelText="取消"
            >
                <Form
                    form={analysisForm}
                    layout="vertical"
                    initialValues={{ limit: 10, engine: 'auto' }}
                >
                    <Form.Item
                        name="limit"
                        label="分析最近记录数"
                        rules={[{ required: true, message: '请输入记录数' }]}
                    >
                        <InputNumber
                            min={1}
                            max={100}
                            style={{ width: '100%' }}
                            placeholder="请输入要分析的记录数"
                        />
                    </Form.Item>
                    <Form.Item
                        name="engine"
                        label="分析引擎"
                    >
                        <Select placeholder="选择分析引擎">
                            <Select.Option value="auto">自动选择</Select.Option>
                            <Select.Option value="k2">AI模型</Select.Option>
                            <Select.Option value="heuristic">启发式</Select.Option>
                        </Select>
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    )
}
