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
    const crawlData = async (days: number = 7, force: boolean = false) => {
        try {
            const r = await fetch(`/api/v1/actions/crawl-data?days=${days}&force=${force}`, { method: 'POST' })
            const js: JobResp = await r.json()
            if (!r.ok) {
                message.error((js as any)?.error || '启动数据爬取失败')
                return
            }

            message.success(`已启动数据爬取任务: ${js.job_id}`)

            // 简单的状态检查
            const checkCrawlProgress = async () => {
                try {
                    const jr = await fetch(`/api/v1/jobs/${js.job_id}`)
                    if (jr.ok) {
                        const jobStatus = await jr.json()
                        if (jobStatus.status === 'completed') {
                            const processed = jobStatus.result?.processed?.length || 0
                            message.success(`数据爬取完成，处理了 ${processed} 个运行`)
                            runs.refetch()
                            analysisStatus.refetch()
                        } else if (jobStatus.status === 'failed') {
                            message.error(`数据爬取失败: ${jobStatus.error || '未知错误'}`)
                        } else {
                            setTimeout(checkCrawlProgress, 3000)
                        }
                    }
                } catch (e) {
                    console.warn('检查爬取进度失败:', e)
                }
            }
            setTimeout(checkCrawlProgress, 2000)
        } catch (e) {
            message.error('启动数据爬取失败：' + String(e))
        }
    }

    return (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Row gutter={16}>
                <Col span={12}>
                    <ChartCard
                        title="UB 总分趋势"
                        option={{
                            tooltip: {
                                trigger: 'axis', formatter: (params: any) => {
                                    const point = params[0]
                                    return `${point.axisValue}<br/>Score: ${point.value}`
                                }
                            },
                            xAxis: {
                                type: 'category',
                                data: (series.data?.series || []).map(p => p.date),
                                axisLabel: { rotate: 45 }
                            },
                            yAxis: {
                                type: 'value',
                                name: 'Score',
                                // 动态调整Y轴范围，突出波动
                                min: (value: any) => {
                                    const values = (series.data?.series || []).map(p => p.value).filter(v => isFinite(v))
                                    if (values.length === 0) return 'dataMin'
                                    const minVal = Math.min(...values)
                                    const maxVal = Math.max(...values)
                                    const range = maxVal - minVal
                                    // 如果变化幅度很小，则扩大显示范围
                                    if (range < maxVal * 0.1) {
                                        return Math.max(0, minVal - maxVal * 0.05)
                                    }
                                    return Math.max(0, minVal - range * 0.1)
                                },
                                max: (value: any) => {
                                    const values = (series.data?.series || []).map(p => p.value).filter(v => isFinite(v))
                                    if (values.length === 0) return 'dataMax'
                                    const minVal = Math.min(...values)
                                    const maxVal = Math.max(...values)
                                    const range = maxVal - minVal
                                    // 如果变化幅度很小，则扩大显示范围
                                    if (range < maxVal * 0.1) {
                                        return maxVal + maxVal * 0.05
                                    }
                                    return maxVal + range * 0.1
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
                            tooltip: { trigger: 'item' },
                            series: [{ type: 'pie', radius: ['40%', '70%'], data: (() => { const sc = summary.data?.severity_counts || { high: 0, medium: 0, low: 0 }; return [{ name: 'high', value: sc.high }, { name: 'medium', value: sc.medium }, { name: 'low', value: sc.low }] })() }]
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
                            yAxis: { type: 'value', name: '% Δ' },
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
                            yAxis: { type: 'category', data: ['high', 'medium', 'low'], splitArea: { show: true } },
                            visualMap: { min: 0, max: Math.max(1, ...(tl.data?.items || []).map(i => Math.max((i as any).high || 0, (i as any).medium || 0, (i as any).low || 0))), calculable: true, orient: 'horizontal', left: 'center', bottom: 0 },
                            series: [{ type: 'heatmap', data: (() => { const items = (tl.data?.items || []); const out: any[] = []; const ys = ['high', 'medium', 'low']; items.forEach((d, xi) => { ys.forEach((y, yi) => { out.push([xi, yi, (d as any)[y] || 0]) }) }); return out })(), emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } } }]
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
                                name: 'Score',
                                nameTextStyle: { fontSize: 14 },
                                // 动态调整Y轴范围以突出箱线图
                                min: (value: any) => {
                                    const arr = (series.data?.series || []).slice(-30).map(p => p.value).filter(v => isFinite(v)).sort((a, b) => a - b)
                                    if (!arr.length) return 'dataMin'
                                    const min = arr[0]
                                    const max = arr[arr.length - 1]
                                    const range = max - min
                                    return Math.max(0, min - range * 0.15)
                                },
                                max: (value: any) => {
                                    const arr = (series.data?.series || []).slice(-30).map(p => p.value).filter(v => isFinite(v)).sort((a, b) => a - b)
                                    if (!arr.length) return 'dataMax'
                                    const min = arr[0]
                                    const max = arr[arr.length - 1]
                                    const range = max - min
                                    return max + range * 0.15
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

            <Row gutter={16}>
                <Col span={24}>
                    <ChartCard
                        title="异常严重度堆叠折线（按日）"
                        option={{
                            tooltip: { trigger: 'axis' },
                            legend: { data: ['high', 'medium', 'low'] },
                            xAxis: { type: 'category', data: (tl.data?.items || []).map(i => i.date) },
                            yAxis: { type: 'value' },
                            series: [
                                { type: 'line', name: 'high', stack: 'sev', areaStyle: {}, data: (tl.data?.items || []).map(i => (i as any).high || 0) },
                                { type: 'line', name: 'medium', stack: 'sev', areaStyle: {}, data: (tl.data?.items || []).map(i => (i as any).medium || 0) },
                                { type: 'line', name: 'low', stack: 'sev', areaStyle: {}, data: (tl.data?.items || []).map(i => (i as any).low || 0) },
                            ]
                        }}
                    />
                </Col>
            </Row>

            <Card title="运行列表">
                <Space direction="vertical" style={{ width: '100%' }} size={12}>
                    <Space wrap>
                        <DatePicker.RangePicker onChange={(v) => { setPage(1); setDateRange(v as any) }} />
                        <Select
                            allowClear
                            placeholder="engine"
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
                        <Input placeholder="patch_id" style={{ width: 160 }} value={patchId} onChange={(e) => {
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
                            options={allColumns.map(k => ({ label: k, value: k }))}
                        />
                        <Button onClick={() => {
                            try {
                                const rows = (runs.data?.runs || [])
                                const cols = visibleCols
                                const csvHeader = cols.join(',')
                                const toCell = (r: any, k: ColumnKey) => {
                                    if (k === 'patch') return `${r.patch_id || ''}/${r.patch_set || ''}`
                                    return r[k] ?? (k === 'engine' ? (r.engine?.name || '') : '')
                                }
                                const csvRows = rows.map(r => cols.map(k => String(toCell(r, k)).replaceAll('"', '""')).map(x => `"${x}"`).join(','))
                                const csv = [csvHeader, ...csvRows].join('\n')
                                const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
                                const url = URL.createObjectURL(blob)
                                const a = document.createElement('a'); a.href = url; a.download = `runs_${Date.now()}.csv`; a.click(); URL.revokeObjectURL(url)
                            } catch (e) { message.error('导出失败') }
                        }}>导出CSV</Button>
                        <Button type="primary" onClick={() => {
                            analysisForm.resetFields()
                            setShowAnalysisModal(true)
                        }} disabled={analysisProgress.visible}>
                            {analysisProgress.visible ? '分析中...' : '智能分析'}
                        </Button>
                        <Button onClick={() => crawlData(7, false)}>获取数据(7天)</Button>
                        <Button onClick={() => crawlData(7, true)}>强制获取数据</Button>
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
                        }}
                        columns={[
                            visibleCols.includes('date') && { title: 'date', dataIndex: 'date', sorter: true },
                            visibleCols.includes('rel') && { title: 'rel', dataIndex: 'rel', render: (v: string) => <Button type="link" onClick={() => props.onOpenRun(v)}>{v.split('/').slice(-1)[0]}</Button> },
                            visibleCols.includes('patch') && { title: 'patch', dataIndex: 'patch_id', sorter: true, render: (_: any, r: any) => `${r.patch_id || ''}/${r.patch_set || ''}` },
                            visibleCols.includes('total_anomalies') && { title: 'anoms', dataIndex: 'total_anomalies', sorter: true },
                            visibleCols.includes('engine') && { title: 'engine', render: (_: any, r: any) => <>{r.engine?.name}{r.engine?.degraded ? <Tag color="orange" style={{ marginLeft: 8 }}>降级</Tag> : null}</> },
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
        </Space>
    )
}


