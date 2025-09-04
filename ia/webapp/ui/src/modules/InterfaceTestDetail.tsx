import React, { useState } from 'react'
import { Card, Row, Col, Table, Tag, Space, Button, Descriptions, Alert, Collapse, List, Typography, Statistic, Progress, Badge, Divider, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftOutlined, CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined, BugOutlined, ToolOutlined, CodeOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

const { Panel } = Collapse
const { Text, Title } = Typography

async function getJSON<T>(url: string): Promise<T> {
    const r = await fetch(url)
    if (!r.ok) throw new Error(String(r.status))
    return r.json()
}

type InterfaceDetailResp = {
    run_dir: string
    rel: string
    meta: {
        date: string
        patch_id: string
        patch_set: string
        test_type: string
        downloaded_at: string
    }
    summary: {
        total_anomalies: number
        severity_counts: {
            high: number
            medium: number
            low: number
        }
        analysis_engine?: {
            name: string
            version: string
        }
        analysis_time?: string
    }
    test_results: Array<{
        case: string
        status: 'PASS' | 'FAIL'
        failure_reason?: string
        execution_time?: number
    }>
    test_summary: {
        total: number
        passed: number
        failed: number
        ignored: number
        success_rate: number
        final_result: string
    }
    anomalies: Array<{
        case: string
        severity: 'high' | 'medium' | 'low'
        description?: string
        suggestion?: string
        confidence?: number
        primary_reason?: string
        root_causes?: Array<{
            cause: string
            likelihood: number
            category?: string
        }>
        suggestions?: string[]
        supporting_evidence?: {
            test_name?: string
            fail_reason?: string
            logfile?: string
            time_elapsed?: number
            test_category?: string
            ai_enhanced?: boolean
        }
    }>
}

interface InterfaceTestDetailProps {
    rel: string
    onBack: () => void
}

export function InterfaceTestDetail({ rel, onBack }: InterfaceTestDetailProps) {
    const [activeTab, setActiveTab] = useState<string>('summary')
    const [pageSize, setPageSize] = useState<number>(20)
    const [currentPage, setCurrentPage] = useState<number>(1)

    // 获取详情数据
    const detail = useQuery<InterfaceDetailResp>({
        queryKey: ['interface-detail', rel],
        queryFn: () => getJSON<InterfaceDetailResp>(`/api/v1/interface/runs/${encodeURIComponent(rel)}`)
    })

    if (detail.isLoading) {
        return <Card loading={true} />
    }

    if (detail.error) {
        return (
            <Card>
                <Alert
                    message="加载失败"
                    description={String(detail.error)}
                    type="error"
                    showIcon
                />
            </Card>
        )
    }

    const data = detail.data!
    const successRate = data.test_summary?.success_rate || 0
    const failedTests = data.test_results?.filter(t => t.status === 'FAIL') || []
    const passedTests = data.test_results?.filter(t => t.status === 'PASS') || []

    // 按组件分组失败的测试
    const failuresByComponent: Record<string, number> = {}
    data.anomalies?.forEach(anomaly => {
        const component = anomaly.case?.split('.')[0] || 'unknown'
        failuresByComponent[component] = (failuresByComponent[component] || 0) + 1
    })

    // 测试结果表格列
    const testColumns = [
        {
            title: '测试用例',
            dataIndex: 'case',
            key: 'case',
            width: 400,
            render: (testCase: string) => (
                <Text code style={{ fontSize: 12 }}>{testCase}</Text>
            )
        },
        {
            title: '状态',
            dataIndex: 'status',
            key: 'status',
            width: 100,
            render: (status: string) => {
                const isPass = status === 'PASS'
                return (
                    <Tag
                        color={isPass ? 'green' : 'red'}
                        icon={isPass ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                    >
                        {status}
                    </Tag>
                )
            }
        },
        {
            title: '失败原因',
            dataIndex: 'failure_reason',
            key: 'failure_reason',
            render: (reason: string, record: any) => {
                if (record.status === 'PASS') {
                    return <span style={{ color: '#999' }}>-</span>
                }
                return reason ? (
                    <Text type="danger" style={{ fontSize: 12 }}>
                        {reason.length > 100 ? `${reason.substring(0, 100)}...` : reason}
                    </Text>
                ) : (
                    <span style={{ color: '#999' }}>无详细信息</span>
                )
            }
        }
    ]

    // 异常分析表格列
    const anomalyColumns = [
        {
            title: '测试用例',
            dataIndex: 'case',
            key: 'case',
            width: 300,
            render: (testCase: string) => (
                <Text code style={{ fontSize: 12 }}>{testCase}</Text>
            )
        },
        {
            title: '严重程度',
            dataIndex: 'severity',
            key: 'severity',
            width: 100,
            render: (severity: string) => {
                const colors = { high: 'red', medium: 'orange', low: 'blue' }
                const labels = { high: '高', medium: '中', low: '低' }
                return (
                    <Tag color={colors[severity as keyof typeof colors]}>
                        {labels[severity as keyof typeof labels] || severity}
                    </Tag>
                )
            }
        },
        {
            title: '问题描述',
            dataIndex: 'description',
            key: 'description',
            render: (desc: string) => (
                <Text style={{ fontSize: 12 }}>{desc}</Text>
            )
        },
        {
            title: '修复建议',
            dataIndex: 'suggestion',
            key: 'suggestion',
            render: (suggestion: string) => (
                suggestion ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>{suggestion}</Text>
                ) : (
                    <span style={{ color: '#999' }}>无建议</span>
                )
            )
        },
        {
            title: '置信度',
            dataIndex: 'confidence',
            key: 'confidence',
            width: 100,
            render: (confidence: number) => {
                if (!confidence) return <span style={{ color: '#999' }}>-</span>
                const percent = Math.round(confidence * 100)
                return (
                    <Progress
                        percent={percent}
                        size="small"
                        format={() => `${percent}%`}
                        status={percent >= 80 ? 'success' : percent >= 60 ? 'normal' : 'exception'}
                    />
                )
            }
        }
    ]

    return (
        <div style={{ padding: 24 }}>
            {/* 页面头部 */}
            <Card size="small" style={{ marginBottom: 16 }}>
                <Row align="middle" justify="space-between">
                    <Col>
                        <Space>
                            <Button
                                icon={<ArrowLeftOutlined />}
                                onClick={onBack}
                            >
                                返回列表
                            </Button>
                            <Divider type="vertical" />
                            <Title level={5} style={{ margin: 0 }}>
                                接口测试详情
                            </Title>
                            <Tag color="blue">P{data.meta?.patch_id}</Tag>
                            <Tag>PS{data.meta?.patch_set}</Tag>
                            <Tag>{dayjs(data.meta?.downloaded_at || data.meta?.date).format('YYYY-MM-DD HH:mm')}</Tag>
                        </Space>
                    </Col>
                    <Col>
                        <Space>
                            {successRate === 100 ? (
                                <Badge status="success" text="全部通过" />
                            ) : (
                                <Badge status="error" text={`${failedTests.length} 个失败`} />
                            )}
                        </Space>
                    </Col>
                </Row>
            </Card>

            {/* 测试概览统计卡片 */}
            <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={4}>
                    <Card size="small">
                        <Statistic
                            title="总测试数"
                            value={data.test_summary?.total || 0}
                            prefix={<CodeOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={4}>
                    <Card size="small">
                        <Statistic
                            title="通过数"
                            value={data.test_summary?.passed || 0}
                            valueStyle={{ color: '#3f8600' }}
                            prefix={<CheckCircleOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={4}>
                    <Card size="small">
                        <Statistic
                            title="失败数"
                            value={data.test_summary?.failed || 0}
                            valueStyle={{ color: '#cf1322' }}
                            prefix={<CloseCircleOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={4}>
                    <Card size="small">
                        <Statistic
                            title="成功率"
                            value={successRate}
                            precision={2}
                            suffix="%"
                            valueStyle={{
                                color: successRate >= 95 ? '#3f8600' :
                                    successRate >= 90 ? '#faad14' : '#cf1322'
                            }}
                            prefix={<ExclamationCircleOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={4}>
                    <Card size="small">
                        <Statistic
                            title="异常数"
                            value={data.anomalies?.length || 0}
                            valueStyle={{ color: (data.anomalies?.length || 0) > 0 ? '#cf1322' : '#3f8600' }}
                            prefix={<BugOutlined />}
                        />
                    </Card>
                </Col>
                <Col span={4}>
                    <Card size="small">
                        <Statistic
                            title="最终结果"
                            value={data.test_summary?.final_result === 'PASSED' ? '通过' : '失败'}
                            valueStyle={{
                                color: data.test_summary?.final_result === 'PASSED' ? '#3f8600' : '#cf1322'
                            }}
                        />
                    </Card>
                </Col>
            </Row>

            {/* 成功率进度条 */}
            <Card size="small" style={{ marginBottom: 16 }}>
                <Title level={5}>测试执行概况</Title>
                <Progress
                    percent={successRate}
                    status={successRate === 100 ? 'success' : successRate < 90 ? 'exception' : 'normal'}
                    strokeColor={{
                        '0%': successRate === 100 ? '#52c41a' : '#f5222d',
                        '100%': successRate === 100 ? '#52c41a' : successRate >= 90 ? '#faad14' : '#f5222d'
                    }}
                    format={(percent) => (
                        <span>
                            {percent?.toFixed(1)}%
                            <br />
                            <small>{passedTests.length}/{data.test_results?.length || 0} 通过</small>
                        </span>
                    )}
                />
            </Card>

            {/* 失败分布（如果有失败） */}
            {failedTests.length > 0 && Object.keys(failuresByComponent).length > 0 && (
                <Card size="small" style={{ marginBottom: 16 }}>
                    <Title level={5}>失败测试分布</Title>
                    <Row gutter={16}>
                        {Object.entries(failuresByComponent).map(([component, count]) => (
                            <Col key={component} span={6}>
                                <Card size="small" type="inner">
                                    <Statistic
                                        title={component}
                                        value={count}
                                        suffix="个失败"
                                        valueStyle={{ color: '#cf1322' }}
                                    />
                                </Card>
                            </Col>
                        ))}
                    </Row>
                </Card>
            )}

            {/* 主要内容区 */}
            <Card>
                {/* 失败测试详情 */}
                {failedTests.length > 0 && (
                    <div style={{ marginBottom: 24 }}>
                        <Title level={5}>
                            <Space>
                                <CloseCircleOutlined style={{ color: '#cf1322' }} />
                                失败的测试用例 ({failedTests.length})
                            </Space>
                        </Title>

                        {/* 如果有AI分析结果，显示异常分析 */}
                        {data.anomalies?.length > 0 ? (
                            <>
                                <Alert
                                    message="AI分析检测到异常"
                                    description={`发现 ${data.anomalies.length} 个测试异常，需要关注`}
                                    type="warning"
                                    showIcon
                                    icon={<BugOutlined />}
                                    style={{ marginBottom: 16 }}
                                />
                                <Collapse defaultActiveKey={data.anomalies.slice(0, 3).map((_, i) => String(i))}>
                                    {data.anomalies.map((anomaly, index) => {
                                        const testCase = failedTests.find(t => t.case === anomaly.case)
                                        const severityColor = {
                                            high: 'red',
                                            medium: 'orange',
                                            low: 'yellow'
                                        }[anomaly.severity] || 'default'

                                        return (
                                            <Panel
                                                key={index}
                                                header={
                                                    <Space>
                                                        <Tag color="red">失败</Tag>
                                                        <Text strong code>{anomaly.case}</Text>
                                                        <Tag color={severityColor}>
                                                            {anomaly.severity === 'high' ? '高' : anomaly.severity === 'medium' ? '中' : '低'}严重度
                                                        </Tag>
                                                        {anomaly.confidence && (
                                                            <Tag>置信度: {(anomaly.confidence * 100).toFixed(0)}%</Tag>
                                                        )}
                                                    </Space>
                                                }
                                            >
                                                <Descriptions bordered size="small" column={1}>
                                                    <Descriptions.Item label="主要原因">
                                                        <Text>{anomaly.primary_reason}</Text>
                                                    </Descriptions.Item>

                                                    {anomaly.root_causes && anomaly.root_causes.length > 0 && (
                                                        <Descriptions.Item label="根因分析">
                                                            <List
                                                                size="small"
                                                                dataSource={anomaly.root_causes}
                                                                renderItem={(cause) => (
                                                                    <List.Item>
                                                                        <Space direction="vertical" style={{ width: '100%' }}>
                                                                            <Text>{cause.cause}</Text>
                                                                            <Progress
                                                                                percent={cause.likelihood && !isNaN(cause.likelihood) && cause.likelihood > 0 ? cause.likelihood * 100 : 50}
                                                                                size="small"
                                                                                format={(percent) => {
                                                                                    if (cause.likelihood && !isNaN(cause.likelihood) && cause.likelihood > 0) {
                                                                                        return `可能性: ${(cause.likelihood * 100).toFixed(0)}%`
                                                                                    } else {
                                                                                        return `可能性: 未知`
                                                                                    }
                                                                                }}
                                                                            />
                                                                            {cause.category && (
                                                                                <Text type="secondary" style={{ fontSize: 12 }}>
                                                                                    类别: {cause.category}
                                                                                </Text>
                                                                            )}
                                                                        </Space>
                                                                    </List.Item>
                                                                )}
                                                            />
                                                        </Descriptions.Item>
                                                    )}

                                                    {anomaly.suggestions && anomaly.suggestions.length > 0 && (
                                                        <Descriptions.Item label="建议检查">
                                                            <List
                                                                size="small"
                                                                dataSource={anomaly.suggestions}
                                                                renderItem={(check, idx) => (
                                                                    <List.Item>
                                                                        <Space>
                                                                            <ToolOutlined />
                                                                            <Text>{check}</Text>
                                                                        </Space>
                                                                    </List.Item>
                                                                )}
                                                            />
                                                        </Descriptions.Item>
                                                    )}

                                                    {anomaly.supporting_evidence?.test_category && (
                                                        <Descriptions.Item label="测试分类">
                                                            <Space>
                                                                <Tag color="blue">{anomaly.supporting_evidence.test_category || '未知组件'}</Tag>
                                                                {anomaly.supporting_evidence.ai_enhanced && (
                                                                    <Tag color="green">AI增强分析</Tag>
                                                                )}
                                                            </Space>
                                                        </Descriptions.Item>
                                                    )}
                                                </Descriptions>
                                            </Panel>
                                        )
                                    })}
                                </Collapse>
                            </>
                        ) : data.summary?.analysis_time ? (
                            /* 已分析但无异常，显示失败用例原始信息 */
                            <>
                                <Alert
                                    message="AI分析完成"
                                    description="AI分析未发现明显异常模式，以下是失败测试用例的详细信息。"
                                    type="info"
                                    showIcon
                                    style={{ marginBottom: 16 }}
                                />
                                <Collapse defaultActiveKey={failedTests.slice(0, 3).map((_, i) => String(i))}>
                                    {failedTests.map((testCase, index) => (
                                        <Panel
                                            key={index}
                                            header={
                                                <Space>
                                                    <Tag color="red">失败</Tag>
                                                    <Text strong code>{testCase.case}</Text>
                                                    <Tag color="blue">已分析</Tag>
                                                </Space>
                                            }
                                        >
                                            <Descriptions bordered size="small" column={1}>
                                                <Descriptions.Item label="失败原因">
                                                    <Text type="danger">{testCase.failure_reason || '无详细信息'}</Text>
                                                </Descriptions.Item>
                                                <Descriptions.Item label="分析结果">
                                                    <Text type="secondary">AI分析未发现明显的异常模式，可能是偶发性问题或环境相关因素。</Text>
                                                </Descriptions.Item>
                                            </Descriptions>
                                        </Panel>
                                    ))}
                                </Collapse>
                            </>
                        ) : (
                            /* 未分析的失败用例 */
                            <>
                                <Alert
                                    message="失败用例待分析"
                                    description="发现失败的测试用例，但尚未进行AI分析。请在列表页面点击分析按钮。"
                                    type="warning"
                                    showIcon
                                    style={{ marginBottom: 16 }}
                                />
                                <Collapse defaultActiveKey={failedTests.slice(0, 3).map((_, i) => String(i))}>
                                    {failedTests.map((testCase, index) => (
                                        <Panel
                                            key={index}
                                            header={
                                                <Space>
                                                    <Tag color="red">失败</Tag>
                                                    <Text strong code>{testCase.case}</Text>
                                                    <Tag color="orange">未分析</Tag>
                                                </Space>
                                            }
                                        >
                                            <Descriptions bordered size="small" column={1}>
                                                <Descriptions.Item label="失败原因">
                                                    <Text type="danger">{testCase.failure_reason || '无详细信息'}</Text>
                                                </Descriptions.Item>
                                                <Descriptions.Item label="分析状态">
                                                    <Alert
                                                        message="未进行AI分析"
                                                        description="该失败测试用例尚未进行AI分析，请在列表页面点击分析按钮。"
                                                        type="info"
                                                        showIcon
                                                        size="small"
                                                    />
                                                </Descriptions.Item>
                                            </Descriptions>
                                        </Panel>
                                    ))}
                                </Collapse>
                            </>
                        )}
                    </div>
                )}

                {/* 如果没有失败的测试 */}
                {failedTests.length === 0 && (
                    <Alert
                        message="所有测试用例均通过"
                        description="恭喜！该测试运行中所有接口测试用例都成功通过。"
                        type="success"
                        showIcon
                        style={{ marginBottom: 16 }}
                    />
                )}

                <Divider />

                {/* 所有测试结果表格 */}
                <div>
                    <Title level={5}>
                        <Space>
                            <CodeOutlined />
                            全部测试结果 ({data.test_results?.length || 0})
                        </Space>
                    </Title>

                    <Table
                        columns={[
                            {
                                title: '序号',
                                width: 80,
                                render: (_, __, index) => index + 1
                            },
                            {
                                title: '测试用例',
                                dataIndex: 'case',
                                key: 'case',
                                render: (name: string) => <Text code>{name}</Text>
                            },
                            {
                                title: '状态',
                                dataIndex: 'status',
                                key: 'status',
                                width: 100,
                                render: (status: string) => (
                                    status === 'PASS' ? (
                                        <Tag color="green" icon={<CheckCircleOutlined />}>通过</Tag>
                                    ) : (
                                        <Tag color="red" icon={<CloseCircleOutlined />}>失败</Tag>
                                    )
                                ),
                                filters: [
                                    { text: '通过', value: 'PASS' },
                                    { text: '失败', value: 'FAIL' }
                                ],
                                onFilter: (value, record) => record.status === value,
                                defaultFilteredValue: failedTests.length > 0 && failedTests.length <= 5 ? ['FAIL'] : undefined
                            }
                        ]}
                        dataSource={data.test_results || []}
                        rowKey="case"
                        size="small"
                        pagination={{
                            current: currentPage,
                            pageSize: pageSize,
                            showSizeChanger: true,
                            showTotal: (total) => `共 ${total} 个测试用例`,
                            onChange: (page, size) => {
                                setCurrentPage(page)
                                setPageSize(size || 20)
                            }
                        }}
                        rowClassName={(record) => record.status === 'FAIL' ? 'ant-table-row-error' : ''}
                        style={{ marginTop: 16 }}
                    />
                </div>

                {/* 分析元信息 */}
                <Divider />
                <Descriptions size="small" column={3}>
                    <Descriptions.Item label="分析引擎">
                        {data.summary?.analysis_engine?.name || 'interface_test_analyzer'}
                    </Descriptions.Item>
                    <Descriptions.Item label="引擎版本">
                        {data.summary?.analysis_engine?.version || '1.0.0'}
                    </Descriptions.Item>
                    <Descriptions.Item label="分析时间">
                        {data.summary?.analysis_time ? dayjs(data.summary.analysis_time).format('YYYY-MM-DD HH:mm:ss') : '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="数据下载时间">
                        {data.meta?.downloaded_at ? dayjs(data.meta.downloaded_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="异常数量">
                        <Space>
                            {data.summary?.severity_counts?.high > 0 && (
                                <Tag color="red">高: {data.summary.severity_counts.high}</Tag>
                            )}
                            {data.summary?.severity_counts?.medium > 0 && (
                                <Tag color="orange">中: {data.summary.severity_counts.medium}</Tag>
                            )}
                            {data.summary?.severity_counts?.low > 0 && (
                                <Tag color="yellow">低: {data.summary.severity_counts.low}</Tag>
                            )}
                            {data.summary?.total_anomalies === 0 && (
                                <Tag color="green">无异常</Tag>
                            )}
                        </Space>
                    </Descriptions.Item>
                </Descriptions>
            </Card>

            {/* 添加自定义样式 */}
            <style>{`
                .ant-table-row-error {
                    background-color: #fff2f0;
                }
                .ant-table-row-error:hover > td {
                    background-color: #ffebe8 !important;
                }
            `}</style>
        </div>
    )
}
