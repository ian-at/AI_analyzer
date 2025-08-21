import React, { useMemo, useState } from 'react'
import { Card, Row, Col, Table, Tag, Space, Button, DatePicker, Select, Input, Switch, message, Modal, Form, InputNumber, Progress } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { ChartCard } from '../components/ChartCard'

async function getJSON<T>(url: string): Promise<T> {
    const r = await fetch(url)
    if (!r.ok) throw new Error(String(r.status))
    return r.json()
}

type RunsResp = { runs: Array<{ rel: string, date: string, patch_id?: string, patch_set?: string, total_anomalies: number, engine?: { name?: string, degraded?: boolean }, analysis_time?: string }>, page: number, page_size: number, total: number }
type SeriesResp = { metric: string, series: Array<{ date: string, value: number }> }
type SummaryResp = { severity_counts: { high: number, medium: number, low: number } }
type TopResp = { items: Array<{ metric: string, pct_change: number }> }
type TLResp = { items: Array<{ date: string, total: number }> }
type MetricsResp = { metrics: string[] }
type AnalysisStatusResp = { last_analysis_time?: string, last_analysis_engine?: string, last_analysis_count?: number, last_analysis_criteria?: string }
type JobResp = { job_id: string }

export function Dashboard(props: { onOpenRun: (rel: string) => void }) {
    // 从 localStorage 恢复分页状态
    const getStoredState = <T,>(key: string, defaultValue: T): T => {
        try {
            const stored = localStorage.getItem(`ia_dashboard_${key}`)
            return stored ? JSON.parse(stored) : defaultValue
        } catch {
            return defaultValue
        }
    }

    const setStoredState = <T,>(key: string, value: T) => {
        try {
            localStorage.setItem(`ia_dashboard_${key}`, JSON.stringify(value))
        } catch {
            // 忽略存储错误
        }
    }

    // 状态：筛选/排序/分页
    const [dateRange, setDateRange] = useState<[any, any] | null>(null)
    const [engine, setEngine] = useState<string | undefined>(getStoredState('engine', undefined))
    const [patchId, setPatchId] = useState<string>(getStoredState('patchId', ''))
    const [abnormalOnly, setAbnormalOnly] = useState<boolean>(getStoredState('abnormalOnly', false))
    const [page, setPage] = useState<number>(getStoredState('page', 1))
    const [pageSize, setPageSize] = useState<number>(getStoredState('pageSize', 20))
    const [sortBy, setSortBy] = useState<'date' | 'total_anomalies' | 'patch_id'>(getStoredState('sortBy', 'date'))
    const [order, setOrder] = useState<'asc' | 'desc'>(getStoredState('order', 'desc'))
    const allColumns = ['date', 'rel', 'patch', 'total_anomalies', 'engine', 'analysis_time', 'actions'] as const
    type ColumnKey = typeof allColumns[number]
    const [visibleCols, setVisibleCols] = useState<ColumnKey[]>(['date', 'rel', 'patch', 'total_anomalies', 'engine', 'analysis_time', 'actions'])

    // 分析相关状态
    const [showAnalysisModal, setShowAnalysisModal] = useState(false)
    const [analysisForm] = Form.useForm()
    const [analysisProgress, setAnalysisProgress] = useState<{ visible: boolean, current: number, total?: number, status?: string }>({ visible: false, current: 0 })
    const [currentJobId, setCurrentJobId] = useState<string | null>(null)
    const [selectedMetric, setSelectedMetric] = useState<string>('System Benchmarks Index Score')

    // 数据获取相关状态
    const [showCrawlModal, setShowCrawlModal] = useState(false)
    const [crawlForm] = Form.useForm()

    const runsUrl = useMemo(() => {
        const params = new URLSearchParams()
        params.set('page', String(page))
        params.set('page_size', String(pageSize))
        params.set('sort_by', sortBy)
        params.set('order', order)
        if (abnormalOnly) params.set('abnormal_only', 'true')
        if (engine && engine.trim()) params.set('engine', engine)
        if (patchId && patchId.trim()) params.set('patch_id', patchId.trim())
        if (dateRange && dateRange[0] && dateRange[1]) {
            try { params.set('start', dateRange[0].format('YYYY-MM-DD')); params.set('end', dateRange[1].format('YYYY-MM-DD')) } catch { /* ignore */ }
        }
        // 根据列选择联动字段裁剪
        const fieldSet = new Set<string>(['rel'])
        if (visibleCols.includes('date')) fieldSet.add('date')
        if (visibleCols.includes('patch')) { fieldSet.add('patch_id'); fieldSet.add('patch_set') }
        if (visibleCols.includes('total_anomalies')) fieldSet.add('total_anomalies')
        if (visibleCols.includes('engine')) fieldSet.add('engine')
        if (visibleCols.includes('analysis_time')) fieldSet.add('analysis_time')
        params.set('fields', Array.from(fieldSet).join(','))
        return `/api/v1/runs?${params.toString()}`
    }, [page, pageSize, sortBy, order, abnormalOnly, engine, patchId, dateRange, visibleCols])

    const runs = useQuery({ queryKey: ['runs', runsUrl], queryFn: () => getJSON<RunsResp>(runsUrl), keepPreviousData: true })
    const [metric, setMetric] = useState<string>('System Benchmarks Index Score')
    const series = useQuery({ queryKey: ['series', metric], queryFn: () => getJSON<SeriesResp>('/api/v1/series?metric=' + encodeURIComponent(metric)) })
    const summary = useQuery({ queryKey: ['summary'], queryFn: () => getJSON<SummaryResp>('/api/v1/anomalies/summary') })
    const top = useQuery({ queryKey: ['top'], queryFn: () => getJSON<TopResp>('/api/v1/top-drifts?window=5&limit=10') })
    const tl = useQuery({ queryKey: ['timeline'], queryFn: () => getJSON<TLResp>('/api/v1/anomalies/timeline') })
    const metrics = useQuery({ queryKey: ['metrics'], queryFn: () => getJSON<MetricsResp>('/api/v1/metrics') })
    const analysisStatus = useQuery({
        queryKey: ['analysis-status'],
        queryFn: () => getJSON<AnalysisStatusResp>('/api/v1/analysis/status'),
        refetchInterval: analysisProgress.visible ? 2000 : false // 分析中时每2秒刷新状态
    })

    // 分析函数
    const startAnalysis = async (values: any) => {
        setShowAnalysisModal(false)
        setAnalysisProgress({ visible: true, current: 0, status: '正在启动分析...' })

        try {
            const params = new URLSearchParams()
            if (values.engine) params.set('engine', values.engine)
            if (values.startDate) params.set('start_date', values.startDate.format('YYYY-MM-DD'))
            if (values.endDate) params.set('end_date', values.endDate.format('YYYY-MM-DD'))
            if (values.limit) params.set('limit', String(values.limit))
            if (values.patchIds) params.set('patch_ids', values.patchIds)

            const url = values.mode === 'recent'
                ? `/api/v1/actions/reanalyze-recent?limit=${values.recentLimit || 10}&no_fallback=${values.engine === 'k2'}`
                : `/api/v1/actions/reanalyze?${params.toString()}`

            const r = await fetch(url, { method: 'POST' })
            const js: JobResp = await r.json()
            if (!r.ok) {
                message.error(js as any)?.error || '启动分析失败'
                setAnalysisProgress({ visible: false, current: 0 })
                return
            }

            setCurrentJobId(js.job_id)
            message.success('分析任务已启动：' + js.job_id)

            // 监控任务进度 - 基于真实任务状态
            const checkProgress = async () => {
                try {
                    const jr = await fetch(`/api/v1/jobs/${js.job_id}`)
                    if (!jr.ok) {
                        if (jr.status === 404) {
                            setAnalysisProgress({ visible: false, current: 0 })
                            message.error('任务不存在或已过期')
                            setCurrentJobId(null)
                            return
                        }
                        throw new Error(`HTTP ${jr.status}`)
                    }

                    const jobStatus = await jr.json()
                    const total = jobStatus.total || jobStatus.result?.total || analysisProgress.total || 0
                    const current = jobStatus.current || 0

                    if (jobStatus.status === 'completed') {
                        setAnalysisProgress({ visible: false, current: 100, total })
                        const processed = jobStatus.result?.processed || 0
                        message.success(`分析完成！处理了 ${processed} 个运行`)
                        // 刷新所有数据
                        runs.refetch()
                        summary.refetch()
                        top.refetch()
                        tl.refetch()
                        analysisStatus.refetch()
                        setCurrentJobId(null)
                    } else if (jobStatus.status === 'failed') {
                        setAnalysisProgress({ visible: false, current: 0 })
                        const errorMsg = jobStatus.error || jobStatus.result?.error || '未知错误'
                        message.error('分析失败：' + errorMsg)
                        setCurrentJobId(null)
                    } else if (jobStatus.status === 'running') {
                        // 显示运行中状态（基于 current/total 真实进度）
                        const percent = total > 0 ? Math.min(99, Math.floor((current / total) * 100)) : 50
                        setAnalysisProgress({ visible: true, current: percent, total, status: jobStatus.message || '正在分析中，请稍候...' })
                        setTimeout(checkProgress, 2000)
                    } else {
                        // pending 状态
                        setAnalysisProgress({ visible: true, current: 10, status: '任务排队中...' })
                        setTimeout(checkProgress, 1000)
                    }
                } catch (e) {
                    console.warn('检查进度失败:', e)
                    setAnalysisProgress(prev => ({ ...prev, status: '检查状态失败，重试中...' }))
                    setTimeout(checkProgress, 5000)
                }
            }

            setTimeout(checkProgress, 2000)
        } catch (e) {
            message.error('启动分析失败：' + String(e))
            setAnalysisProgress({ visible: false, current: 0 })
        }
    }

    // 单个运行重新分析
    const reanalyzeSingleRun = async (rel: string, engine: string = 'auto') => {
        try {
            const r = await fetch(`/api/v1/runs/${encodeURIComponent(rel)}/reanalyze?engine=${engine}`, { method: 'POST' })
            const js: JobResp & { rel: string } = await r.json()
            if (!r.ok) {
                message.error((js as any)?.error || '启动单个分析失败')
                return
            }

            message.success(`已启动分析任务: ${js.job_id}`)

            // 简单的状态检查，无进度条
            const checkSingleProgress = async () => {
                try {
                    const jr = await fetch(`/api/v1/jobs/${js.job_id}`)
                    if (jr.ok) {
                        const jobStatus = await jr.json()
                        if (jobStatus.status === 'completed') {
                            message.success(`运行 ${rel.split('/').pop()} 分析完成`)
                            runs.refetch()
                            analysisStatus.refetch()
                        } else if (jobStatus.status === 'failed') {
                            message.error(`运行 ${rel.split('/').pop()} 分析失败: ${jobStatus.error || '未知错误'}`)
                        } else {
                            setTimeout(checkSingleProgress, 3000)
                        }
                    }
                } catch (e) {
                    console.warn('检查单个分析进度失败:', e)
                }
            }
            setTimeout(checkSingleProgress, 2000)
        } catch (e) {
            message.error('启动单个分析失败：' + String(e))
        }
    }

    // 数据爬取
    const startCrawlData = async (values: any) => {
        setShowCrawlModal(false)
        try {
            const r = await fetch(`/api/v1/actions/crawl-data?days=${values.days}&force=${values.force}`, { method: 'POST' })
            const js: JobResp = await r.json()
            if (!r.ok) {
                message.error((js as any)?.error || '启动数据获取失败')
                return
            }

            const actionType = values.force ? '重新解析' : '获取'
            message.success(`已启动数据${actionType}任务: ${js.job_id}`)

            // 简单的状态检查
            const checkCrawlProgress = async () => {
                try {
                    const jr = await fetch(`/api/v1/jobs/${js.job_id}`)
                    if (jr.ok) {
                        const jobStatus = await jr.json()
                        if (jobStatus.status === 'completed') {
                            const processed = jobStatus.result?.processed?.length || 0
                            message.success(`数据${actionType}完成，处理了 ${processed} 个运行`)
                            runs.refetch()
                            analysisStatus.refetch()
                        } else if (jobStatus.status === 'failed') {
                            message.error(`数据${actionType}失败: ${jobStatus.error || '未知错误'}`)
                        } else {
                            setTimeout(checkCrawlProgress, 3000)
                        }
                    }
                } catch (e) {
                    console.warn('检查进度失败:', e)
                }
            }
            setTimeout(checkCrawlProgress, 2000)
        } catch (e) {
            message.error('启动数据操作失败：' + String(e))
        }
    }

    return (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Row gutter={16}>
                <Col span={12}>
                    <ChartCard
                        title={(() => {
                            const values = (series.data?.series || []).map(p => p.value).filter(v => isFinite(v))
                            if (values.length === 0) return "UB 总分趋势"
                            const minVal = Math.min(...values)
                            const maxVal = Math.max(...values)
                            return `UB 总分趋势 (最高: ${maxVal.toFixed(1)}, 最低: ${minVal.toFixed(1)})`
                        })()}
                        option={{
                            tooltip: {
                                trigger: 'axis', formatter: (params: any) => {
                                    const point = params[0]
                                    return `${point.axisValue}<br/>得分: ${point.value}`
                                }
                            },
                            xAxis: {
                                type: 'category',
                                data: (series.data?.series || []).map(p => p.date),
                                axisLabel: { rotate: 45 }
                            },
                            yAxis: {
                                type: 'value',
                                name: '得分',
                                // 动态调整Y轴范围，突出波动
                                min: (value: any) => {
                                    const values = (series.data?.series || []).map(p => p.value).filter(v => isFinite(v))
                                    if (values.length === 0) return 0
                                    const minVal = Math.min(...values)
                                    const maxVal = Math.max(...values)
                                    const range = maxVal - minVal
                                    // 如果变化幅度很小，则扩大显示范围
                                    if (range < 1) {
                                        const result = Math.max(0, minVal - 5)
                                        return Math.round(result * 100) / 100  // 精确到小数点后2位
                                    }
                                    const result = Math.max(0, minVal - range * 0.1)
                                    return Math.round(result * 100) / 100  // 精确到小数点后2位
                                },
                                max: (value: any) => {
                                    const values = (series.data?.series || []).map(p => p.value).filter(v => isFinite(v))
                                    if (values.length === 0) return 100
                                    const minVal = Math.min(...values)
                                    const maxVal = Math.max(...values)
                                    const range = maxVal - minVal
                                    // 如果变化幅度很小，则扩大显示范围
                                    if (range < 1) {
                                        const result = maxVal + 5
                                        return Math.round(result * 100) / 100  // 精确到小数点后2位
                                    }
                                    const result = maxVal + range * 0.1
                                    return Math.round(result * 100) / 100  // 精确到小数点后2位
                                }
                            },
                            series: [{
                                type: 'line',
                                smooth: true,
                                data: (series.data?.series || []).map(p => p.value),
                                lineStyle: { width: 2 },
                                symbol: 'circle',
                                symbolSize: 6,
                                emphasis: { focus: 'series' }
                            }]
                        }}
                    />
                </Col>
                <Col span={12}>
                    <ChartCard
                        title="异常占比"
                        option={{
                            tooltip: {
                                trigger: 'item',
                                formatter: (params: any) => {
                                    const { name, value, percent } = params
                                    return `${name}: ${value} 个 (${percent}%)`
                                }
                            },
                            legend: {
                                bottom: 10,
                                formatter: (name: string) => {
                                    const sc = summary.data?.severity_counts || { high: 0, medium: 0, low: 0 }
                                    const counts = { high: sc.high, medium: sc.medium, low: sc.low }
                                    return `${name} (${(counts as any)[name] || 0})`
                                }
                            },
                            series: [{
                                type: 'pie',
                                radius: ['40%', '70%'],
                                data: (() => {
                                    const sc = summary.data?.severity_counts || { high: 0, medium: 0, low: 0 }
                                    return [
                                        { name: '高危', value: sc.high },
                                        { name: '中危', value: sc.medium },
                                        { name: '低危', value: sc.low }
                                    ]
                                })(),
                                label: {
                                    formatter: (params: any) => {
                                        const { name, value, percent } = params
                                        return `${name}\n${value} (${percent}%)`
                                    }
                                }
                            }]
                        }}
                    />
                </Col>
            </Row>

            <Row gutter={16}>
                <Col span={24}>
                    <Space wrap>
                        <span>指标</span>
                        <Select
                            showSearch
                            style={{ minWidth: 360 }}
                            placeholder="选择指标（末尾为指标名，如 System Benchmarks Index Score）"
                            value={metric}
                            onChange={(v) => setMetric(v)}
                            options={(metrics.data?.metrics || []).map(k => ({ label: k, value: k.split('::').slice(-1)[0] }))}
                            filterOption={(input, option) => (option?.label as string).toLowerCase().includes(input.toLowerCase())}
                        />
                    </Space>
                </Col>
            </Row>
            <Row gutter={16}>
                <Col span={12}>
                    <ChartCard
                        title="Top-N 波动指标"
                        option={{
                            tooltip: {},
                            xAxis: { type: 'category', data: (top.data?.items || []).map(i => i.metric.split('::').slice(-1)[0]) },
                            yAxis: { type: 'value', name: '百分比变化' },
                            series: [{ type: 'bar', data: (top.data?.items || []).map(i => Math.round(i.pct_change * 1000) / 10) }]
                        }}
                    />
                </Col>
                <Col span={12}>
                    <ChartCard
                        title="异常时间轴"
                        option={{
                            tooltip: { trigger: 'axis' },
                            xAxis: { type: 'category', data: (tl.data?.items || []).map(i => i.date) },
                            yAxis: { type: 'value' },
                            series: [{ type: 'line', smooth: true, data: (tl.data?.items || []).map(i => i.total) }]
                        }}
                    />
                </Col>
            </Row>

            <Row gutter={16}>
                <Col span={24}>
                    <ChartCard
                        title="异常热力图（日期×严重度）"
                        option={{
                            tooltip: { position: 'top' },
                            grid: { height: '60%', top: '10%' },
                            xAxis: { type: 'category', data: (tl.data?.items || []).map(i => i.date), splitArea: { show: true } },
                            yAxis: { type: 'category', data: ['高危', '中危', '低危'], splitArea: { show: true } },
                            visualMap: { min: 0, max: Math.max(1, ...(tl.data?.items || []).map(i => Math.max((i as any).high || 0, (i as any).medium || 0, (i as any).low || 0))), calculable: true, orient: 'horizontal', left: 'center', bottom: 0 },
                            series: [{ type: 'heatmap', data: (() => { const items = (tl.data?.items || []); const out: any[] = []; const ys = ['high', 'medium', 'low']; items.forEach((d, xi) => { ys.forEach((y, yi) => { out.push([xi, yi, (d as any)[y] || 0]) }) }); return out })(), emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } } }]
                        }}
                    />
                </Col>
            </Row>

            <Row gutter={16}>
                <Col span={24}>
                    <ChartCard
                        title="异常严重度堆叠折线（按日）"
                        option={{
                            tooltip: { trigger: 'axis' },
                            legend: { data: ['高危', '中危', '低危'] },
                            xAxis: { type: 'category', data: (tl.data?.items || []).map(i => i.date) },
                            yAxis: { type: 'value' },
                            series: [
                                { type: 'line', name: '高危', stack: 'sev', areaStyle: {}, data: (tl.data?.items || []).map(i => (i as any).high || 0) },
                                { type: 'line', name: '中危', stack: 'sev', areaStyle: {}, data: (tl.data?.items || []).map(i => (i as any).medium || 0) },
                                { type: 'line', name: '低危', stack: 'sev', areaStyle: {}, data: (tl.data?.items || []).map(i => (i as any).low || 0) },
                            ]
                        }}
                    />
                </Col>
            </Row>

            <Row gutter={16}>
                <Col span={24}>
                    <ChartCard
                        title="UB 总分箱线图（最近30点）"
                        option={{
                            tooltip: {
                                trigger: 'item',
                                formatter: (params: any) => {
                                    if (params.componentType === 'series' && params.seriesType === 'boxplot') {
                                        const [min, q1, median, q3, max] = params.value
                                        return `
                                            最大值: ${max}<br/>
                                            75%分位: ${q3}<br/>
                                            中位数: ${median}<br/>
                                            25%分位: ${q1}<br/>
                                            最小值: ${min}
                                        `
                                    }
                                    return ''
                                }
                            },
                            grid: { left: 80, right: 40, top: 40, bottom: 60 },
                            xAxis: {
                                type: 'category',
                                data: ['总分分布'],
                                axisLabel: { fontSize: 14 }
                            },
                            yAxis: {
                                type: 'value',
                                name: '得分',
                                nameTextStyle: { fontSize: 14 },
                                // 动态调整Y轴范围以突出箱线图
                                min: (value: any) => {
                                    const arr = (series.data?.series || []).slice(-30).map(p => p.value).filter(v => isFinite(v)).sort((a, b) => a - b)
                                    if (!arr.length) return 0
                                    const min = arr[0]
                                    const max = arr[arr.length - 1]
                                    const range = max - min
                                    // 如果变化幅度很小，使用固定偏移
                                    if (range < 1) {
                                        const result = Math.max(0, min - 2)
                                        return Math.round(result * 100) / 100  // 精确到小数点后2位
                                    }
                                    const result = Math.max(0, min - range * 0.15)
                                    return Math.round(result * 100) / 100  // 精确到小数点后2位
                                },
                                max: (value: any) => {
                                    const arr = (series.data?.series || []).slice(-30).map(p => p.value).filter(v => isFinite(v)).sort((a, b) => a - b)
                                    if (!arr.length) return 100
                                    const min = arr[0]
                                    const max = arr[arr.length - 1]
                                    const range = max - min
                                    // 如果变化幅度很小，使用固定偏移
                                    if (range < 1) {
                                        const result = max + 2
                                        return Math.round(result * 100) / 100  // 精确到小数点后2位
                                    }
                                    const result = max + range * 0.15
                                    return Math.round(result * 100) / 100  // 精确到小数点后2位
                                }
                            },
                            series: [{
                                type: 'boxplot',
                                data: (() => {
                                    const arr = (series.data?.series || []).slice(-30).map(p => p.value).filter(v => isFinite(v)).sort((a, b) => a - b)
                                    if (!arr.length) return []
                                    const q = (p: number) => {
                                        const index = (arr.length - 1) * p
                                        const lower = Math.floor(index)
                                        const upper = Math.ceil(index)
                                        const weight = index % 1
                                        return arr[lower] * (1 - weight) + arr[upper] * weight
                                    }
                                    const min = arr[0]
                                    const max = arr[arr.length - 1]
                                    const q1 = q(0.25)
                                    const q2 = q(0.5)  // 中位数
                                    const q3 = q(0.75)
                                    return [[min, q1, q2, q3, max]]
                                })(),
                                boxWidth: ['20%', '20%'],  // 设置箱体宽度
                                itemStyle: {
                                    borderColor: '#1677ff',
                                    borderWidth: 2
                                },
                                emphasis: {
                                    itemStyle: {
                                        borderColor: '#40a9ff',
                                        borderWidth: 3
                                    }
                                }
                            }]
                        }}
                    />
                </Col>
            </Row>

            <Card title="运行列表">
                <Space direction="vertical" style={{ width: '100%' }} size={12}>
                    <Space wrap>
                        <DatePicker.RangePicker
                            placeholder={['开始日期', '结束日期']}
                            onChange={(v) => { setPage(1); setDateRange(v as any) }}
                        />
                        <Select
                            allowClear
                            placeholder="分析引擎"
                            style={{ minWidth: 160 }}
                            options={[{ value: 'kimi-k2', label: 'kimi-k2' }, { value: 'heuristic', label: 'heuristic' }]}
                            value={engine}
                            onChange={(v) => {
                                setPage(1);
                                setStoredState('page', 1);
                                setEngine(v);
                                setStoredState('engine', v);
                            }}
                        />
                        <Input placeholder="补丁ID" style={{ width: 160 }} value={patchId} onChange={(e) => {
                            setPage(1);
                            setStoredState('page', 1);
                            setPatchId(e.target.value);
                            setStoredState('patchId', e.target.value);
                        }} />
                        <span>仅异常</span>
                        <Switch checked={abnormalOnly} onChange={(v) => {
                            setPage(1);
                            setStoredState('page', 1);
                            setAbnormalOnly(v);
                            setStoredState('abnormalOnly', v);
                        }} />
                        <Select
                            mode="multiple"
                            style={{ minWidth: 220 }}
                            value={visibleCols}
                            onChange={(v) => setVisibleCols(v as ColumnKey[])}
                            options={allColumns.map(k => ({
                                label: k === 'date' ? '日期' :
                                    k === 'rel' ? '运行ID' :
                                        k === 'patch' ? '补丁' :
                                            k === 'total_anomalies' ? '异常数' :
                                                k === 'engine' ? '引擎' :
                                                    k === 'analysis_time' ? '分析时间' :
                                                        k === 'actions' ? '操作' : k,
                                value: k
                            }))}
                        />

                        <Button onClick={async () => {
                            try {
                                // 分批获取所有数据
                                const batchSize = 100 // 每次获取100条记录
                                let allRows: any[] = []
                                let page = 1
                                let hasMore = true

                                while (hasMore) {
                                    const params = new URLSearchParams()
                                    params.set('page', String(page))
                                    params.set('page_size', String(batchSize))
                                    params.set('sort_by', sortBy)
                                    params.set('order', order)
                                    if (abnormalOnly) params.set('abnormal_only', 'true')
                                    if (engine && engine.trim()) params.set('engine', engine)
                                    if (patchId && patchId.trim()) params.set('patch_id', patchId.trim())
                                    if (dateRange && dateRange[0] && dateRange[1]) {
                                        try { params.set('start', dateRange[0].format('YYYY-MM-DD')); params.set('end', dateRange[1].format('YYYY-MM-DD')) } catch { /* ignore */ }
                                    }
                                    // 确保获取所有必要字段
                                    params.set('fields', 'rel,date,patch_id,patch_set,total_anomalies,engine,analysis_time')

                                    const batchUrl = `/api/v1/runs?${params.toString()}`
                                    const response = await fetch(batchUrl)
                                    if (!response.ok) {
                                        throw new Error(`获取数据失败: ${response.status}`)
                                    }
                                    const batchData = await response.json()
                                    const batchRows = batchData.runs || []

                                    allRows = allRows.concat(batchRows)

                                    // 检查是否还有更多数据
                                    if (batchRows.length < batchSize) {
                                        hasMore = false
                                    } else {
                                        page++
                                    }

                                    // 防止无限循环，最多获取5000条记录
                                    if (allRows.length >= 5000) {
                                        message.warning('数据量过大，仅导出前5000条记录')
                                        hasMore = false
                                    }
                                }

                                const rows = allRows

                                if (rows.length === 0) {
                                    message.warning('没有数据可导出')
                                    return
                                }

                                // 过滤掉 actions 列，只导出数据列
                                const exportCols = visibleCols.filter(k => k !== 'actions')

                                // 转换列名为中文表头
                                const headerMap: Record<ColumnKey, string> = {
                                    'date': '日期',
                                    'rel': '运行ID',
                                    'patch': '补丁',
                                    'total_anomalies': '异常数',
                                    'engine': '分析引擎',
                                    'analysis_time': '分析时间',
                                    'actions': '操作'
                                }

                                const toCell = (r: any, k: ColumnKey) => {
                                    switch (k) {
                                        case 'date':
                                            return r.date || ''
                                        case 'rel':
                                            // 提取运行ID部分，去掉日期前缀 (如：2025-08-16/run_p2299_ps1 -> run_p2299_ps1)
                                            const rel = r.rel || ''
                                            const parts = rel.split('/')
                                            return parts.length > 1 ? parts[1] : rel
                                        case 'patch':
                                            // 使用Excel文本格式标识符，防止自动转换为日期
                                            const patchValue = `${r.patch_id || ''}/${r.patch_set || ''}`
                                            return `="${patchValue}"`
                                        case 'engine':
                                            const engineName = r.engine?.name || ''
                                            const degraded = r.engine?.degraded ? '(降级)' : ''
                                            return engineName + degraded
                                        case 'analysis_time':
                                            return r.analysis_time ? new Date(r.analysis_time).toLocaleString('zh-CN') : ''
                                        case 'total_anomalies':
                                            return r.total_anomalies || 0
                                        default:
                                            return r[k] || ''
                                    }
                                }

                                // 使用CSV格式，但确保每个字段正确分离
                                const headers = exportCols.map(k => headerMap[k] || k)
                                const csvHeader = headers.join(',')

                                const csvRows = rows.map(r =>
                                    exportCols.map(k => {
                                        const value = String(toCell(r, k))
                                        // 正确处理CSV转义：包含逗号、引号或换行符的字段用双引号包围
                                        if (value.includes(',') || value.includes('"') || value.includes('\n') || value.includes('\r')) {
                                            return `"${value.replace(/"/g, '""')}"`
                                        }
                                        return value
                                    }).join(',')
                                )

                                const csvContent = [csvHeader, ...csvRows].join('\n')

                                // 添加BOM以确保中文正确显示，使用正确的CSV MIME类型
                                const BOM = '\uFEFF'
                                const blob = new Blob([BOM + csvContent], {
                                    type: 'text/csv;charset=utf-8'
                                })

                                const url = URL.createObjectURL(blob)
                                const timestamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-')
                                const a = document.createElement('a')
                                a.href = url
                                a.download = `UB分析数据_${timestamp}.csv`
                                a.click()
                                URL.revokeObjectURL(url)
                                message.success(`已导出Excel兼容文件 ${rows.length} 条记录`)
                            } catch (e) {
                                console.error('Excel导出错误:', e)
                                message.error('Excel导出失败: ' + String(e))
                            }
                        }}>导出Excel</Button>
                        <Button type="primary" onClick={() => {
                            analysisForm.resetFields()
                            setShowAnalysisModal(true)
                        }} disabled={analysisProgress.visible}>
                            {analysisProgress.visible ? '分析中...' : '智能分析'}
                        </Button>
                        <Button onClick={() => {
                            crawlForm.resetFields()
                            setShowCrawlModal(true)
                        }}>数据获取与解析</Button>
                        {analysisStatus.data?.last_analysis_time && (
                            <span style={{ fontSize: '12px', color: '#666' }}>
                                最后分析: {new Date(analysisStatus.data.last_analysis_time).toLocaleString()}
                                ({analysisStatus.data.last_analysis_engine})
                                处理了{analysisStatus.data.last_analysis_count}个
                            </span>
                        )}
                    </Space>

                    <Table
                        dataSource={(runs.data?.runs || []).map((r, idx) => ({ key: `${r.rel}-${idx}`, ...r }))}
                        size="small"
                        loading={runs.isLoading}
                        onChange={(pg, _filters, sorter: any) => {
                            // 分页
                            const newPage = pg.current || 1
                            const newPageSize = pg.pageSize || 20
                            setPage(newPage)
                            setPageSize(newPageSize)
                            setStoredState('page', newPage)
                            setStoredState('pageSize', newPageSize)
                            // 排序
                            const f = sorter.field as string | undefined
                            const ord = sorter.order as ('ascend' | 'descend' | undefined)
                            if (f && ord) {
                                if (f === 'date' || f === 'total_anomalies' || f === 'patch_id') {
                                    setSortBy(f as any)
                                    setStoredState('sortBy', f)
                                }
                                const newOrder = ord === 'ascend' ? 'asc' : 'desc'
                                setOrder(newOrder)
                                setStoredState('order', newOrder)
                            }
                        }}
                        pagination={{
                            current: runs.data?.page || page,
                            pageSize: runs.data?.page_size || pageSize,
                            total: runs.data?.total || 0,
                            showSizeChanger: true,
                            showTotal: (total: number, range: [number, number]) => `第 ${range[0]}-${range[1]} 条，共 ${total} 条`,
                        }}
                        columns={[
                            visibleCols.includes('date') && { title: '日期', dataIndex: 'date', sorter: true },
                            visibleCols.includes('rel') && { title: '运行ID', dataIndex: 'rel', render: (v: string) => <Button type="link" onClick={() => props.onOpenRun(v)}>{v.split('/').slice(-1)[0]}</Button> },
                            visibleCols.includes('patch') && { title: '补丁', dataIndex: 'patch_id', sorter: true, render: (_: any, r: any) => `${r.patch_id || ''}/${r.patch_set || ''}` },
                            visibleCols.includes('total_anomalies') && { title: '异常数', dataIndex: 'total_anomalies', sorter: true },
                            visibleCols.includes('engine') && { title: '引擎', render: (_: any, r: any) => <>{r.engine?.name}{r.engine?.degraded ? <Tag color="orange" style={{ marginLeft: 8 }}>降级</Tag> : null}</> },
                            visibleCols.includes('analysis_time') && {
                                title: '分析时间',
                                dataIndex: 'analysis_time',
                                render: (time: string) => time ? new Date(time).toLocaleString() : '-'
                            },
                            visibleCols.includes('actions') && {
                                title: '操作',
                                key: 'actions',
                                render: (_: any, r: any) => {
                                    const analyzed = !!(r.engine && r.engine.name) || !!r.analysis_time
                                    const label = analyzed ? '重新分析' : '分析'
                                    return (
                                        <Space size="small">
                                            <Button size="small" onClick={() => reanalyzeSingleRun(r.rel, 'auto')}>
                                                {label}
                                            </Button>
                                        </Space>
                                    )
                                }
                            },
                        ].filter(Boolean) as any}
                    />
                </Space>
            </Card>

            {/* 分析进度条 */}
            {analysisProgress.visible && (
                <Card>
                    <Space direction="vertical" style={{ width: '100%' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span>分析进度:</span>
                            <Progress percent={analysisProgress.current} style={{ flex: 1 }} />
                            {analysisProgress.total != null && (
                                <span style={{ minWidth: 120, textAlign: 'right', color: '#666' }}>
                                    {Math.min(analysisProgress.current, 99)}% ({Math.min(analysisProgress.total || 0, Math.max(analysisProgress.current, 0))}/{analysisProgress.total})
                                </span>
                            )}
                            {currentJobId && <Button size="small" danger onClick={() => {
                                setAnalysisProgress({ visible: false, current: 0 })
                                setCurrentJobId(null)
                                message.info('已取消监控')
                            }}>取消监控</Button>}
                        </div>
                        {analysisProgress.status && <div style={{ color: '#666', fontSize: '12px' }}>{analysisProgress.status}</div>}
                    </Space>
                </Card>
            )}

            {/* 分析配置模态框 */}
            <Modal
                title="智能分析配置"
                open={showAnalysisModal}
                onCancel={() => setShowAnalysisModal(false)}
                onOk={() => analysisForm.submit()}
                width={600}
            >
                <Form
                    form={analysisForm}
                    layout="vertical"
                    onFinish={startAnalysis}
                    initialValues={{
                        mode: 'recent',
                        engine: 'auto',
                        recentLimit: 10
                    }}
                >
                    <Form.Item>
                        <Space>
                            <Button
                                type="primary"
                                onClick={async () => {
                                    try {
                                        const engine = analysisForm.getFieldValue('engine') || 'auto'
                                        const r = await fetch(`/api/v1/actions/reanalyze-all-missing?engine=${encodeURIComponent(engine)}`, { method: 'POST' })
                                        const js: JobResp = await r.json()
                                        if (!r.ok) {
                                            message.error((js as any)?.error || '启动分析所有失败')
                                            return
                                        }
                                        setShowAnalysisModal(false)
                                        setCurrentJobId(js.job_id)
                                        setAnalysisProgress({ visible: true, current: 0, status: '正在分析所有未分析的运行...' })
                                        // 复用同一进度轮询
                                        const check = async () => {
                                            try {
                                                const jr = await fetch(`/api/v1/jobs/${js.job_id}`)
                                                if (jr.ok) {
                                                    const s = await jr.json()
                                                    const total = s.total || s.result?.total || 0
                                                    const current = s.current || 0
                                                    if (s.status === 'completed') {
                                                        setAnalysisProgress({ visible: false, current: 100, total })
                                                        const processed = s.result?.processed?.length || s.result?.processed || 0
                                                        message.success(`分析完成，处理 ${processed}/${total}`)
                                                        runs.refetch(); summary.refetch(); top.refetch(); tl.refetch(); analysisStatus.refetch()
                                                        setCurrentJobId(null)
                                                    } else if (s.status === 'failed') {
                                                        setAnalysisProgress({ visible: false, current: 0 })
                                                        message.error('分析失败：' + (s.error || '未知错误'))
                                                        setCurrentJobId(null)
                                                    } else {
                                                        const percent = total > 0 ? Math.min(99, Math.floor((current / total) * 100)) : 50
                                                        setAnalysisProgress({ visible: true, current: percent, total, status: s.message || '运行中...' })
                                                        setTimeout(check, 2000)
                                                    }
                                                }
                                            } catch (e) {
                                                setTimeout(check, 4000)
                                            }
                                        }
                                        setTimeout(check, 1500)
                                    } catch (e) {
                                        message.error('启动分析所有失败：' + String(e))
                                    }
                                }}
                            >
                                分析所有（仅未分析）
                            </Button>
                        </Space>
                    </Form.Item>
                    <Form.Item name="mode" label="分析模式">
                        <Select>
                            <Select.Option value="recent">最近N个运行</Select.Option>
                            <Select.Option value="custom">自定义范围</Select.Option>
                        </Select>
                    </Form.Item>

                    <Form.Item name="engine" label="分析引擎">
                        <Select>
                            <Select.Option value="auto">自动选择 (K2优先，降级到启发式)</Select.Option>
                            <Select.Option value="k2">K2 AI引擎 (仅K2)</Select.Option>
                            <Select.Option value="heuristic">启发式引擎 (无AI)</Select.Option>
                        </Select>
                    </Form.Item>

                    <Form.Item
                        noStyle
                        shouldUpdate={(prev, curr) => prev.mode !== curr.mode}
                    >
                        {({ getFieldValue }) => {
                            const mode = getFieldValue('mode')
                            if (mode === 'recent') {
                                return (
                                    <Form.Item name="recentLimit" label="运行数量">
                                        <InputNumber min={1} max={100} placeholder="最近多少个运行" />
                                    </Form.Item>
                                )
                            } else {
                                return (
                                    <>
                                        <Form.Item label="时间范围">
                                            <Input.Group compact>
                                                <Form.Item name="startDate" style={{ display: 'inline-block', width: '48%' }}>
                                                    <DatePicker placeholder="开始日期" style={{ width: '100%' }} />
                                                </Form.Item>
                                                <span style={{ display: 'inline-block', width: '4%', textAlign: 'center', lineHeight: '32px' }}>~</span>
                                                <Form.Item name="endDate" style={{ display: 'inline-block', width: '48%' }}>
                                                    <DatePicker placeholder="结束日期" style={{ width: '100%' }} />
                                                </Form.Item>
                                            </Input.Group>
                                        </Form.Item>

                                        <Form.Item name="limit" label="限制数量 (可选)">
                                            <InputNumber min={1} max={500} placeholder="最多处理多少个" />
                                        </Form.Item>

                                        <Form.Item name="patchIds" label="指定Patch ID (可选)">
                                            <Input.TextArea
                                                placeholder="逗号分隔的patch_id列表，例如: abc123,def456"
                                                rows={2}
                                            />
                                        </Form.Item>
                                    </>
                                )
                            }
                        }}
                    </Form.Item>
                </Form>
            </Modal>

            {/* 数据管理模态框 */}
            <Modal
                title="数据获取与解析"
                open={showCrawlModal}
                onCancel={() => setShowCrawlModal(false)}
                onOk={() => crawlForm.submit()}
                width={500}
            >
                <Form
                    form={crawlForm}
                    layout="vertical"
                    onFinish={startCrawlData}
                    initialValues={{
                        days: 7,
                        force: false
                    }}
                >
                    <Form.Item name="days" label="获取天数" rules={[{ required: true, message: '请输入天数' }]}>
                        <InputNumber
                            min={1}
                            max={3650}
                            placeholder="请输入要获取数据的天数"
                            style={{ width: '100%' }}
                            addonAfter="天"
                        />
                    </Form.Item>

                    <Form.Item name="force" label="处理模式" rules={[{ required: true }]}>
                        <Select placeholder="选择处理模式">
                            <Select.Option value={false}>增量获取（跳过已解析数据）</Select.Option>
                            <Select.Option value={true}>强制重新解析（覆盖现有数据）</Select.Option>
                        </Select>
                    </Form.Item>

                    <div style={{ color: '#666', fontSize: '12px', marginTop: 16 }}>
                        <div>💡 <strong>增量获取</strong>：仅处理尚未解析的数据，节省时间</div>
                        <div>⚠️ <strong>强制重新解析</strong>：重新处理所有数据，覆盖现有结果</div>
                        <div style={{ marginTop: 8 }}>
                            <strong>建议天数：</strong>
                            <span style={{ marginLeft: 8 }}>日常更新: 7天 | 补齐数据: 30-90天 | 完整历史: 365天+</span>
                        </div>
                    </div>
                </Form>
            </Modal>
        </Space>
    )
}
