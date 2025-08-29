import React, { useMemo, useState } from 'react'
import { Card, Row, Col, Table, Tag, Space, Button, DatePicker, Select, Input, Switch, message, Modal, Form, InputNumber, Progress, Statistic, Alert, Spin, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined, ReloadOutlined, SearchOutlined, FileTextOutlined, DownloadOutlined, ThunderboltOutlined, LineChartOutlined, BarChartOutlined, PieChartOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { ChartCard } from '../components/ChartCard'

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
    total_tests: number[]
    passed_tests: number[]
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
    const analyzeSingleRun = async (rel: string, forceReanalyze: boolean = false) => {
        try {
            setSingleAnalysisLoading(rel)

            // 根据是否强制重新分析选择不同的API端点
            const endpoint = forceReanalyze
                ? `/api/v1/unit/runs/${encodeURIComponent(rel)}/reanalyze`
                : `/api/v1/unit/runs/${encodeURIComponent(rel)}/analyze`

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
            {/* 概览卡片 */}
            <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}>
                    <Card>
                        <Statistic
                            title="总测试运行"
                            value={summary.data?.total_runs || 0}
                            suffix="次"
                            valueStyle={{ color: '#1890ff' }}
                            prefix={<BarChartOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={6}>
                    <Card>
                        <Statistic
                            title="平均成功率"
                            value={summary.data?.average_success_rate || 0}
                            precision={1}
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
                            title="总通过测试"
                            value={summary.data?.total_passed || 0}
                            suffix="个"
                            valueStyle={{ color: '#3f8600' }}
                            prefix={<CheckCircleOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={6}>
                    <Card>
                        <Statistic
                            title="总失败测试"
                            value={summary.data?.total_failed || 0}
                            suffix="个"
                            valueStyle={{ color: '#cf1322' }}
                            prefix={<CloseCircleOutlined />}
                        />
                    </Card>
                </Col>
            </Row>

            {/* 图表区域 */}
            <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={12}>
                    <ChartCard
                        title={(() => {
                            const trendData = trend.data?.success_rates || []
                            if (trendData.length === 0) return "单元测试成功率趋势"
                            const latest = trendData[trendData.length - 1]
                            const previous = trendData.length > 1 ? trendData[trendData.length - 2] : latest
                            const change = latest - previous
                            const changeText = change > 0 ? `↑${change.toFixed(1)}%` : change < 0 ? `↓${Math.abs(change).toFixed(1)}%` : '持平'
                            return `单元测试成功率趋势 (${changeText})`
                        })()}
                        option={{
                            tooltip: {
                                trigger: 'axis',
                                formatter: (params: any) => {
                                    const param = params[0]
                                    const value = param.value
                                    let quality = ''
                                    if (value >= 95) quality = ' 🟢 优秀'
                                    else if (value >= 90) quality = ' 🟡 良好'
                                    else if (value >= 80) quality = ' 🟠 一般'
                                    else quality = ' 🔴 需改进'
                                    return `${param.name}<br/>成功率: ${value?.toFixed(1)}%${quality}`
                                }
                            },
                            legend: {
                                show: false
                            },
                            grid: { left: '3%', right: '15%', bottom: '3%', top: '5%', containLabel: true },
                            xAxis: {
                                type: 'category',
                                data: trend.data?.dates || [],
                                axisLabel: {
                                    rotate: 45,
                                    formatter: (value: string) => dayjs(value).format('MM-DD')
                                }
                            },
                            yAxis: {
                                type: 'value',
                                min: 0,
                                max: 100,
                                axisLabel: {
                                    formatter: '{value}%'
                                },
                                splitLine: {
                                    show: true,
                                    lineStyle: {
                                        color: ['#f0f0f0']
                                    }
                                }
                            },
                            graphic: [
                                // 简化的质量等级指示器
                                {
                                    type: 'group',
                                    right: 15,
                                    top: 50,
                                    children: [
                                        // 质量等级标题
                                        {
                                            type: 'text',
                                            style: {
                                                text: '质量等级',
                                                x: 0, y: 0,
                                                fontSize: 12,
                                                fontWeight: 'bold',
                                                fill: '#666'
                                            }
                                        },
                                        // 优秀
                                        {
                                            type: 'circle',
                                            shape: { cx: 5, cy: 25, r: 6 },
                                            style: { fill: '#52c41a' }
                                        },
                                        {
                                            type: 'text',
                                            style: {
                                                text: '优秀',
                                                x: 18, y: 25,
                                                textBaseline: 'middle',
                                                fontSize: 11,
                                                fill: '#333'
                                            }
                                        },
                                        {
                                            type: 'text',
                                            style: {
                                                text: '95%-100%',
                                                x: 50, y: 25,
                                                textBaseline: 'middle',
                                                fontSize: 10,
                                                fill: '#999'
                                            }
                                        },
                                        // 良好
                                        {
                                            type: 'circle',
                                            shape: { cx: 5, cy: 50, r: 6 },
                                            style: { fill: '#faad14' }
                                        },
                                        {
                                            type: 'text',
                                            style: {
                                                text: '良好',
                                                x: 18, y: 50,
                                                textBaseline: 'middle',
                                                fontSize: 11,
                                                fill: '#333'
                                            }
                                        },
                                        {
                                            type: 'text',
                                            style: {
                                                text: '90%-95%',
                                                x: 50, y: 50,
                                                textBaseline: 'middle',
                                                fontSize: 10,
                                                fill: '#999'
                                            }
                                        },
                                        // 一般
                                        {
                                            type: 'circle',
                                            shape: { cx: 5, cy: 75, r: 6 },
                                            style: { fill: '#ff9c6e' }
                                        },
                                        {
                                            type: 'text',
                                            style: {
                                                text: '一般',
                                                x: 18, y: 75,
                                                textBaseline: 'middle',
                                                fontSize: 11,
                                                fill: '#333'
                                            }
                                        },
                                        {
                                            type: 'text',
                                            style: {
                                                text: '80%-90%',
                                                x: 50, y: 75,
                                                textBaseline: 'middle',
                                                fontSize: 10,
                                                fill: '#999'
                                            }
                                        },
                                        // 需改进
                                        {
                                            type: 'circle',
                                            shape: { cx: 5, cy: 100, r: 6 },
                                            style: { fill: '#ff4d4f' }
                                        },
                                        {
                                            type: 'text',
                                            style: {
                                                text: '需改进',
                                                x: 18, y: 100,
                                                textBaseline: 'middle',
                                                fontSize: 11,
                                                fill: '#333'
                                            }
                                        },
                                        {
                                            type: 'text',
                                            style: {
                                                text: '<80%',
                                                x: 60, y: 100,
                                                textBaseline: 'middle',
                                                fontSize: 10,
                                                fill: '#999'
                                            }
                                        }
                                    ]
                                }
                            ],
                            series: [{
                                name: '成功率',
                                type: 'line',
                                smooth: true,
                                symbol: 'circle',
                                symbolSize: 8,
                                data: trend.data?.success_rates || [],
                                lineStyle: {
                                    width: 4,
                                    color: {
                                        type: 'linear',
                                        x: 0, y: 0, x2: 1, y2: 0,
                                        colorStops: [
                                            { offset: 0, color: '#1890ff' },
                                            { offset: 1, color: '#52c41a' }
                                        ]
                                    }
                                },
                                itemStyle: {
                                    color: (params: any) => {
                                        const value = params.value
                                        if (value >= 95) return '#52c41a'  // 绿色 - 优秀
                                        if (value >= 90) return '#faad14'  // 黄色 - 良好
                                        if (value >= 80) return '#ff9c6e'  // 橙色 - 一般
                                        return '#ff4d4f'  // 红色 - 需改进
                                    }
                                },
                                areaStyle: {
                                    color: {
                                        type: 'linear',
                                        x: 0, y: 0, x2: 0, y2: 1,
                                        colorStops: [
                                            { offset: 0, color: 'rgba(24, 144, 255, 0.2)' },
                                            { offset: 1, color: 'rgba(24, 144, 255, 0.02)' }
                                        ]
                                    }
                                }
                            }]
                        }}
                        height={320}
                    />
                </Col>
                <Col span={12}>
                    <ChartCard
                        title="测试分类失败分布"
                        option={(() => {
                            const categories = failureDist.data?.categories || []
                            const hasFailures = categories.length > 0 && categories.some(cat => cat.count > 0)

                            if (!hasFailures) {
                                // 没有失败时显示友好的"全部通过"状态
                                return {
                                    graphic: [
                                        {
                                            type: 'group',
                                            left: 'center',
                                            top: 'center',
                                            children: [
                                                // 大的绿色圆圈
                                                {
                                                    type: 'circle',
                                                    shape: { cx: 0, cy: 0, r: 60 },
                                                    style: {
                                                        fill: {
                                                            type: 'radial',
                                                            x: 0.5, y: 0.5, r: 0.5,
                                                            colorStops: [
                                                                { offset: 0, color: '#52c41a' },
                                                                { offset: 1, color: '#389e0d' }
                                                            ]
                                                        },
                                                        shadowBlur: 20,
                                                        shadowColor: 'rgba(82, 196, 26, 0.3)'
                                                    }
                                                },
                                                // 对勾图标
                                                {
                                                    type: 'text',
                                                    style: {
                                                        text: '✓',
                                                        x: 0, y: 0,
                                                        textAlign: 'center',
                                                        textBaseline: 'middle',
                                                        fontSize: 40,
                                                        fontWeight: 'bold',
                                                        fill: '#fff'
                                                    }
                                                },
                                                // "全部通过"文字
                                                {
                                                    type: 'text',
                                                    style: {
                                                        text: '全部通过',
                                                        x: 0, y: 80,
                                                        textAlign: 'center',
                                                        textBaseline: 'middle',
                                                        fontSize: 16,
                                                        fontWeight: 'bold',
                                                        fill: '#52c41a'
                                                    }
                                                },
                                                // "无失败测试"说明文字
                                                {
                                                    type: 'text',
                                                    style: {
                                                        text: '无失败测试',
                                                        x: 0, y: 100,
                                                        textAlign: 'center',
                                                        textBaseline: 'middle',
                                                        fontSize: 12,
                                                        fill: '#999'
                                                    }
                                                }
                                            ]
                                        }
                                    ]
                                }
                            } else {
                                // 有失败时显示正常的饼图
                                return {
                                    tooltip: {
                                        trigger: 'item',
                                        formatter: (params: any) => {
                                            const { name, value, percent } = params
                                            return `${name}<br/>失败次数: ${value} 次<br/>占比: ${percent}%`
                                        }
                                    },
                                    legend: {
                                        type: 'scroll',
                                        orient: 'vertical',
                                        right: 10,
                                        top: 20,
                                        bottom: 20
                                    },
                                    series: [{
                                        name: '失败分布',
                                        type: 'pie',
                                        radius: ['40%', '70%'],
                                        center: ['40%', '50%'],
                                        avoidLabelOverlap: false,
                                        label: {
                                            show: false,
                                            position: 'center'
                                        },
                                        emphasis: {
                                            label: {
                                                show: true,
                                                fontSize: 16,
                                                fontWeight: 'bold'
                                            }
                                        },
                                        labelLine: { show: false },
                                        data: categories.map((cat, index) => ({
                                            value: cat.count,
                                            name: cat.name,
                                            itemStyle: {
                                                color: [
                                                    '#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#feca57',
                                                    '#ff9ff3', '#54a0ff', '#5f27cd', '#00d2d3', '#ff9f43'
                                                ][index % 10]
                                            }
                                        }))
                                    }]
                                }
                            }
                        })()}
                        height={320}
                    />
                </Col>
            </Row>

            {/* 第二行图表 */}
            <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={8}>
                    <ChartCard
                        title="测试执行量趋势"
                        option={{
                            tooltip: {
                                trigger: 'axis',
                                formatter: (params: any) => {
                                    const param = params[0]
                                    return `${param.name}<br/>测试数量: ${param.value} 个`
                                }
                            },
                            grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
                            xAxis: {
                                type: 'category',
                                data: trend.data?.dates || [],
                                axisLabel: {
                                    rotate: 45,
                                    formatter: (value: string) => dayjs(value).format('MM-DD')
                                }
                            },
                            yAxis: {
                                type: 'value',
                                axisLabel: {
                                    formatter: '{value}'
                                }
                            },
                            series: [{
                                name: '测试总数',
                                type: 'bar',
                                data: trend.data?.total_tests || [],
                                itemStyle: {
                                    color: {
                                        type: 'linear',
                                        x: 0, y: 0, x2: 0, y2: 1,
                                        colorStops: [
                                            { offset: 0, color: '#1890ff' },
                                            { offset: 1, color: '#40a9ff' }
                                        ]
                                    }
                                },
                                emphasis: {
                                    itemStyle: { color: '#096dd9' }
                                }
                            }]
                        }}
                        height={280}
                    />
                </Col>
                <Col span={8}>
                    <ChartCard
                        title="通过/失败对比"
                        option={{
                            tooltip: {
                                trigger: 'axis',
                                formatter: (params: any) => {
                                    let result = `${params[0].name}<br/>`
                                    params.forEach((param: any) => {
                                        result += `${param.seriesName}: ${param.value} 个<br/>`
                                    })
                                    return result
                                }
                            },
                            legend: {
                                data: ['通过', '失败'],
                                top: 10
                            },
                            grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
                            xAxis: {
                                type: 'category',
                                data: trend.data?.dates || [],
                                axisLabel: {
                                    rotate: 45,
                                    formatter: (value: string) => dayjs(value).format('MM-DD')
                                }
                            },
                            yAxis: {
                                type: 'value'
                            },
                            series: [
                                {
                                    name: '通过',
                                    type: 'bar',
                                    stack: 'total',
                                    data: trend.data?.passed_tests || [],
                                    itemStyle: { color: '#52c41a' }
                                },
                                {
                                    name: '失败',
                                    type: 'bar',
                                    stack: 'total',
                                    data: trend.data?.failed_counts || [],
                                    itemStyle: { color: '#ff4d4f' }
                                }
                            ]
                        }}
                        height={280}
                    />
                </Col>
                <Col span={8}>
                    <ChartCard
                        title="质量趋势指标"
                        option={{
                            tooltip: {
                                trigger: 'axis'
                            },
                            legend: {
                                data: ['成功率', '稳定性指数'],
                                top: 10
                            },
                            grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
                            xAxis: {
                                type: 'category',
                                data: trend.data?.dates || [],
                                axisLabel: {
                                    rotate: 45,
                                    formatter: (value: string) => dayjs(value).format('MM-DD')
                                }
                            },
                            yAxis: [
                                {
                                    type: 'value',
                                    name: '成功率 (%)',
                                    min: 0,
                                    max: 100,
                                    axisLabel: {
                                        formatter: '{value}%'
                                    }
                                },
                                {
                                    type: 'value',
                                    name: '稳定性',
                                    min: 0,
                                    max: 10,
                                    axisLabel: {
                                        formatter: '{value}'
                                    }
                                }
                            ],
                            series: [
                                {
                                    name: '成功率',
                                    type: 'line',
                                    yAxisIndex: 0,
                                    data: trend.data?.success_rates || [],
                                    smooth: true,
                                    lineStyle: { width: 3, color: '#52c41a' },
                                    itemStyle: { color: '#52c41a' }
                                },
                                {
                                    name: '稳定性指数',
                                    type: 'line',
                                    yAxisIndex: 1,
                                    data: (trend.data?.success_rates || []).map((rate, index, arr) => {
                                        // 计算稳定性指数：基于成功率的变化幅度
                                        if (index === 0) return 8
                                        const change = Math.abs(rate - arr[index - 1])
                                        return Math.max(1, 10 - change * 2) // 变化越小，稳定性越高
                                    }),
                                    smooth: true,
                                    lineStyle: { width: 2, color: '#1890ff', type: 'dashed' },
                                    itemStyle: { color: '#1890ff' }
                                }
                            ]
                        }}
                        height={280}
                    />
                </Col>
            </Row>



            {/* 测试质量热力图 */}
            <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={24}>
                    <ChartCard
                        title="单元测试质量热力图（日期×成功率区间）"
                        option={{
                            tooltip: {
                                position: 'top',
                                formatter: (params: any) => {
                                    const { value } = params
                                    const [dateIndex, rateIndex, count] = value
                                    const date = trend.data?.dates[dateIndex] || ''
                                    const rateRanges = ['优秀 (95-100%)', '良好 (90-95%)', '一般 (80-90%)', '较差 (<80%)']
                                    const range = rateRanges[rateIndex] || ''
                                    return `${dayjs(date).format('YYYY-MM-DD')}<br/>${range}<br/>运行次数: ${count}`
                                }
                            },
                            grid: { height: '70%', top: '10%' },
                            xAxis: {
                                type: 'category',
                                data: (trend.data?.dates || []).map(date => dayjs(date).format('MM-DD')),
                                splitArea: { show: true }
                            },
                            yAxis: {
                                type: 'category',
                                data: ['优秀 (95-100%)', '良好 (90-95%)', '一般 (80-90%)', '较差 (<80%)'],
                                splitArea: { show: true }
                            },
                            visualMap: {
                                min: 0,
                                max: Math.max(1, ...(trend.data?.success_rates || []).map(() => 1)), // 简化为0-1范围
                                calculable: true,
                                orient: 'horizontal',
                                left: 'center',
                                bottom: 0,
                                inRange: {
                                    color: ['#fff5f5', '#ffebee', '#ffcdd2', '#ef9a9a', '#e57373', '#ef5350', '#f44336']
                                }
                            },
                            series: [{
                                name: '测试质量',
                                type: 'heatmap',
                                data: (() => {
                                    const dates = trend.data?.dates || []
                                    const rates = trend.data?.success_rates || []
                                    const result: [number, number, number][] = []

                                    dates.forEach((date, dateIndex) => {
                                        const rate = rates[dateIndex] || 0
                                        // 根据成功率确定质量区间
                                        let rateIndex = 3 // 默认较差
                                        if (rate >= 95) rateIndex = 0      // 优秀
                                        else if (rate >= 90) rateIndex = 1  // 良好  
                                        else if (rate >= 80) rateIndex = 2  // 一般

                                        result.push([dateIndex, rateIndex, 1])
                                    })

                                    return result
                                })(),
                                emphasis: {
                                    itemStyle: {
                                        shadowBlur: 10,
                                        shadowColor: 'rgba(0,0,0,0.3)'
                                    }
                                }
                            }]
                        }}
                        height={200}
                    />
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