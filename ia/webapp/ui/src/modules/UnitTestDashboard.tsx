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

type UnitRunsResp = {
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
    }>
    page: number
    page_size: number
    total: number
}

type UnitSummaryResp = {
    total_runs: number
    total_passed: number
    total_failed: number
    average_success_rate: number
    recent_trend: 'improving' | 'stable' | 'declining'
}

type UnitTrendResp = {
    dates: string[]
    success_rates: number[]
    failed_counts: number[]
}

type UnitFailureDistResp = {
    categories: Array<{
        name: string
        count: number
        percentage: number
    }>
}

type JobResp = {
    job_id: string
}

export function UnitTestDashboard(props: { onOpenRun: (rel: string) => void }) {
    // 状态管理
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

    // 构建查询URL
    const runsUrl = useMemo(() => {
        const params = new URLSearchParams()
        params.set('page', String(page))
        params.set('page_size', String(pageSize))
        params.set('test_type', 'unit')

        if (failedOnly) params.set('failed_only', 'true')
        if (patchId && patchId.trim()) params.set('patch_id', patchId.trim())
        if (dateRange && dateRange[0] && dateRange[1]) {
            try {
                params.set('start', dateRange[0].format('YYYY-MM-DD'))
                params.set('end', dateRange[1].format('YYYY-MM-DD'))
            } catch { /* ignore */ }
        }

        return `/api/v1/unit/runs?${params.toString()}`
    }, [page, pageSize, failedOnly, patchId, dateRange])

    // 数据获取
    const runs = useQuery<UnitRunsResp>({
        queryKey: ['unit-runs', runsUrl],
        queryFn: () => getJSON<UnitRunsResp>(runsUrl),
        placeholderData: (previousData) => previousData
    })

    const summary = useQuery<UnitSummaryResp>({
        queryKey: ['unit-summary'],
        queryFn: () => getJSON<UnitSummaryResp>('/api/v1/unit/summary')
    })

    const trend = useQuery<UnitTrendResp>({
        queryKey: ['unit-trend'],
        queryFn: () => getJSON<UnitTrendResp>('/api/v1/unit/trend')
    })

    const failureDist = useQuery<UnitFailureDistResp>({
        queryKey: ['unit-failure-dist'],
        queryFn: () => getJSON<UnitFailureDistResp>('/api/v1/unit/failure-distribution')
    })

    // 处理函数
    const handleCrawl = async () => {
        try {
            const values = await crawlForm.validateFields()
            const data: JobResp = await postJSON('/api/v1/unit/crawl', {
                days: values.days || 7,
                patch_id: values.patch_id
            })

            setCurrentJobId(data.job_id)
            message.success('已开始获取单元测试数据')
            setShowCrawlModal(false)
            crawlForm.resetFields()

            // 轮询任务状态
            pollJobStatus(data.job_id)
        } catch (error) {
            message.error('获取数据失败: ' + String(error))
        }
    }

    const handleAnalysis = async () => {
        try {
            const values = await analysisForm.validateFields()
            const data: JobResp = await postJSON('/api/v1/unit/analyze', {
                days: values.days || 7,
                force: values.force || false
            })

            setCurrentJobId(data.job_id)
            message.success('已开始分析单元测试数据')
            setShowAnalysisModal(false)
            analysisForm.resetFields()

            // 轮询任务状态
            pollJobStatus(data.job_id)
        } catch (error) {
            message.error('分析失败: ' + String(error))
        }
    }

    // 分析单个运行
    const analyzeSingleRun = async (rel: string) => {
        try {
            setSingleAnalysisLoading(rel)
            const data: JobResp = await postJSON(`/api/v1/unit/runs/${encodeURIComponent(rel)}/analyze`, {})

            message.success('已开始分析单个测试运行')

            // 轮询任务状态
            pollJobStatus(data.job_id, () => {
                setSingleAnalysisLoading(null)
            })
        } catch (error) {
            message.error('分析失败: ' + String(error))
            setSingleAnalysisLoading(null)
        }
    }

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
                    trend.refetch()
                    failureDist.refetch()
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

    // 表格列定义
    const columns = [
        {
            title: '日期',
            dataIndex: 'date',
            key: 'date',
            width: 120,
            render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm')
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
                            {rate.toFixed(1)}%
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
                        format={(percent) => `${percent?.toFixed(0)}%`}
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

                // 如果成功率是100%，不显示分析状态
                if (successRate >= 100) {
                    return null
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
                const showAnalyzeButton = successRate < 100 // 只有成功率小于100%才显示分析按钮

                return (
                    <Space size="small">
                        {showAnalyzeButton && (
                            <Button
                                size="small"
                                type={analyzed ? 'default' : 'primary'}
                                icon={<ThunderboltOutlined />}
                                onClick={() => analyzeSingleRun(r.rel)}
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

    // 如果数据加载中，显示加载状态
    if (runs.isLoading || summary.isLoading) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
                <Spin size="large" tip="加载中..." />
            </div>
        )
    }

    // 如果加载失败，显示错误信息
    if (runs.error || summary.error) {
        return (
            <div style={{ padding: 24 }}>
                <Alert
                    message="加载失败"
                    description={String(runs.error || summary.error)}
                    type="error"
                    showIcon
                />
            </div>
        )
    }

    // 计算趋势图标
    const getTrendIcon = () => {
        const trend = summary.data?.recent_trend
        if (trend === 'improving') return '↑'
        if (trend === 'declining') return '↓'
        return '→'
    }

    const getTrendColor = () => {
        const trend = summary.data?.recent_trend
        if (trend === 'improving') return '#52c41a'
        if (trend === 'declining') return '#f5222d'
        return '#1890ff'
    }

    return (
        <div style={{ padding: 24 }}>
            {/* 暂时注释掉图表，避免错误
            <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={14}>
                    <ChartCard
                        title="成功率趋势"
                        loading={trend.isLoading}
                        data={{
                            labels: trend.data?.dates || [],
                            datasets: [{
                                label: '成功率 (%)',
                                data: trend.data?.success_rates || [],
                                borderColor: 'rgb(75, 192, 192)',
                                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                                tension: 0.1,
                                fill: true
                            }]
                        }}
                        options={{
                            responsive: true,
                            plugins: {
                                legend: {
                                    display: true,
                                    position: 'top' as const
                                },
                                title: {
                                    display: false
                                },
                                tooltip: {
                                    callbacks: {
                                        label: function (context: any) {
                                            return `成功率: ${context.parsed.y?.toFixed(1)}%`
                                        }
                                    }
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    max: 100,
                                    ticks: {
                                        callback: function (value: any) {
                                            return value + '%'
                                        }
                                    }
                                }
                            }
                        }}
                    />
                </Col>
                <Col span={10}>
                    <ChartCard
                        title="失败分布 (最近7天)"
                        loading={failureDist.isLoading}
                        type="bar"
                        data={{
                            labels: failureDist.data?.categories.map(c => c.name) || [],
                            datasets: [{
                                label: '失败次数',
                                data: failureDist.data?.categories.map(c => c.count) || [],
                                backgroundColor: [
                                    'rgba(255, 99, 132, 0.5)',
                                    'rgba(255, 159, 64, 0.5)',
                                    'rgba(255, 205, 86, 0.5)',
                                    'rgba(75, 192, 192, 0.5)',
                                    'rgba(54, 162, 235, 0.5)',
                                    'rgba(153, 102, 255, 0.5)',
                                    'rgba(201, 203, 207, 0.5)'
                                ],
                                borderColor: [
                                    'rgb(255, 99, 132)',
                                    'rgb(255, 159, 64)',
                                    'rgb(255, 205, 86)',
                                    'rgb(75, 192, 192)',
                                    'rgb(54, 162, 235)',
                                    'rgb(153, 102, 255)',
                                    'rgb(201, 203, 207)'
                                ],
                                borderWidth: 1
                            }]
                        }}
                        options={{
                            responsive: true,
                            plugins: {
                                legend: {
                                    display: false
                                },
                                title: {
                                    display: false
                                },
                                tooltip: {
                                    callbacks: {
                                        afterLabel: function (context: any) {
                                            const percentage = failureDist.data?.categories[context.dataIndex]?.percentage
                                            return percentage ? `占比: ${percentage}%` : ''
                                        }
                                    }
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true
                                }
                            }
                        }}
                    />
                </Col>
            </Row>
            */}

            {/* 统计卡片 */}
            <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}>
                    <Card size="small">
                        <Statistic
                            title="总运行次数"
                            value={summary.data?.total_runs || 0}
                            prefix={<FileTextOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={6}>
                    <Card size="small">
                        <Statistic
                            title="全部通过"
                            value={summary.data?.total_passed || 0}
                            valueStyle={{ color: '#3f8600' }}
                            prefix={<CheckCircleOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={6}>
                    <Card size="small">
                        <Statistic
                            title="存在失败"
                            value={summary.data?.total_failed || 0}
                            valueStyle={{ color: '#cf1322' }}
                            prefix={<CloseCircleOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={6}>
                    <Card size="small">
                        <Statistic
                            title="平均成功率"
                            value={summary.data?.average_success_rate || 0}
                            precision={1}
                            suffix={
                                <span style={{ fontSize: 14 }}>
                                    % <span style={{ color: getTrendColor() }}>{getTrendIcon()}</span>
                                </span>
                            }
                            valueStyle={{
                                color: (summary.data?.average_success_rate || 0) >= 90 ? '#3f8600' : '#cf1322'
                            }}
                        />
                    </Card>
                </Col>
            </Row>

            {/* 主要内容区 */}
            <Card
                title="单元测试运行记录"
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
                                trend.refetch()
                                failureDist.refetch()
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
                title="获取单元测试数据"
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
                            placeholder="例如：7"
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
                title="AI分析单元测试"
                open={showAnalysisModal}
                onCancel={() => setShowAnalysisModal(false)}
                onOk={handleAnalysis}
                okText="开始分析"
                cancelText="取消"
            >
                <Form
                    form={analysisForm}
                    layout="vertical"
                    initialValues={{ days: 7, force: false }}
                >
                    <Form.Item
                        name="days"
                        label="分析最近天数"
                        rules={[{ required: true, message: '请输入天数' }]}
                    >
                        <InputNumber
                            min={1}
                            max={30}
                            style={{ width: '100%' }}
                            placeholder="例如：7"
                        />
                    </Form.Item>
                    <Form.Item
                        name="force"
                        valuePropName="checked"
                    >
                        <Switch checkedChildren="强制重新分析" unCheckedChildren="跳过已分析" />
                    </Form.Item>
                    <Alert
                        message="分析说明"
                        description="AI将分析失败的测试用例，识别根因并提供修复建议。已分析的数据默认会跳过，选择强制重新分析会重新处理所有数据。"
                        type="info"
                        showIcon
                    />
                </Form>
            </Modal>
        </div>
    )
}