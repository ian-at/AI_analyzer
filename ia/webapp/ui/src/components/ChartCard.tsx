import React, { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { Card } from 'antd'

export function ChartCard(props: { title: string, option: any, height?: number }) {
    const ref = useRef<HTMLDivElement | null>(null)
    const inst = useRef<echarts.ECharts | null>(null)

    useEffect(() => {
        if (!ref.current) return
        if (!inst.current) {
            inst.current = echarts.init(ref.current)
        }
        inst.current.setOption(props.option as any, true)
        const onResize = () => inst.current && inst.current.resize()
        window.addEventListener('resize', onResize)
        return () => { window.removeEventListener('resize', onResize) }
    }, [props.option])

    return (
        <Card title={props.title} style={{ width: '100%' }}>
            <div ref={ref} style={{ width: '100%', height: props.height || 300 }} />
        </Card>
    )
}


