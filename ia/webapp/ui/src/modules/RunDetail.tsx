import React, { useMemo, useState } from 'react'
import { Card, Space, Button, Table, Descriptions, Tag, Switch } from 'antd'
import { useQuery } from '@tanstack/react-query'

async function getJSON<T>(url: string): Promise<T> {
    const r = await fetch(url)
    if (!r.ok) throw new Error(String(r.status))
    return r.json()
}

type RunResp = {
    rel: string
    meta: { date?: string, patch_id?: string, patch_set?: string }
    summary: { total_anomalies: number, analysis_engine?: { name?: string, degraded?: boolean } }
    anomalies: Array<{ suite?: string, case?: string, metric?: string, current_value?: number, severity?: string, confidence?: number, primary_reason?: string }>
    ub: Array<{ metric: string, value: number }>
}

export function RunDetail(props: { rel: string, onBack: () => void }) {
    const encodeRel = (rel: string) => (rel || '').split('/').map(encodeURIComponent).join('/')
    const safeRel = useMemo(() => encodeRel(props.rel), [props.rel])
    const { data } = useQuery({ queryKey: ['run', props.rel], queryFn: () => getJSON<RunResp>('/api/v1/run/' + safeRel) })
    const [embed, setEmbed] = useState<boolean>(true)
    return (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Button onClick={() => {
                // 标记为内部导航，避免滚动恢复
                if ((window as any).__markInternalNav) {
                    (window as any).__markInternalNav()
                }
                props.onBack()
            }}>返回</Button>
            <Card title={`Run ${data?.rel || ''}`}>
                <Descriptions size="small" column={2} bordered>
                    <Descriptions.Item label="日期">{data?.meta?.date || '-'}</Descriptions.Item>
                    <Descriptions.Item label="Patch">{data?.meta?.patch_id || ''}/{data?.meta?.patch_set || ''}</Descriptions.Item>
                    <Descriptions.Item label="总异常">{data?.summary?.total_anomalies || 0}</Descriptions.Item>
                    <Descriptions.Item label="引擎">
                        {data?.summary?.analysis_engine?.name || '-'}
                        {data?.summary?.analysis_engine?.degraded ? <Tag color="orange" style={{ marginLeft: 8 }}>降级</Tag> : null}
                    </Descriptions.Item>
                </Descriptions>
                <div style={{ marginTop: 8 }}>
                    <a href={`/files/${encodeRel(data?.rel || props.rel)}/report.html`} target="_blank">打开 HTML 报告</a>
                </div>
            </Card>
            <Card
                title={
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <span>报告预览（内嵌）</span>
                        <span style={{ fontSize: 12, color: '#666' }}>切换</span>
                        <Switch checked={embed} onChange={setEmbed} />
                        <span style={{ fontSize: 12, color: '#666' }}>{embed ? '内嵌显示 report.html' : '关闭内嵌（可通过上方链接在新窗口打开）'}</span>
                    </div>
                }
            >
                {embed && (
                    <iframe
                        src={`/files/${encodeRel(data?.rel || props.rel)}/report.html`}

                        title="report-preview" style={{ width: '100%', height: 800, border: '1px solid #eee', borderRadius: 6 }}
                    />
                )}
            </Card>
            <Card title="AI 摘要">
                <div>
                    {(data?.anomalies || []).length ? (
                        <>
                            <div style={{ marginBottom: 8 }}>以下为 K2/启发式识别出的异常摘要与根因建议（详细可点击 HTML 报告查看富文本排版）：</div>
                        </>
                    ) : '暂无异常摘要（可点击上方“分析/重新分析”后刷新）'}
                </div>
            </Card>
            <Card title="异常列表">
                <Table dataSource={(data?.anomalies || []).map((a, i) => ({ key: i, ...a }))} size="small" pagination={{ pageSize: 10 }} columns={[
                    { title: 'suite', dataIndex: 'suite' },
                    { title: 'case', dataIndex: 'case' },
                    { title: 'metric', dataIndex: 'metric' },
                    { title: 'value', dataIndex: 'current_value' },
                    { title: 'severity', dataIndex: 'severity' },
                    { title: 'confidence', dataIndex: 'confidence' },
                    { title: 'reason', dataIndex: 'primary_reason' },
                ]} />
            </Card>
        </Space>
    )
}


