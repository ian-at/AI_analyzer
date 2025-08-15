import { useEffect, useRef } from 'react'

/**
 * 滚动位置恢复 Hook
 * 在页面离开时保存滚动位置，返回时恢复
 */
export function useScrollRestore() {
    const isInternalNavRef = useRef(false)

    useEffect(() => {
        const key = `ia_scroll_${location.pathname}${location.search}`

        // 禁用浏览器默认的滚动恢复，我们手动控制
        try {
            if ('scrollRestoration' in history) {
                history.scrollRestoration = 'manual'
            }
        } catch (e) {
            // 忽略错误
        }

        const saveScroll = () => {
            try {
                const y = window.scrollY || window.pageYOffset || 0
                sessionStorage.setItem(key, String(y))
            } catch (e) {
                // 忽略存储错误
            }
        }

        const restoreScroll = (force = false) => {
            try {
                const savedY = parseInt(sessionStorage.getItem(key) || '0', 10)
                if (savedY > 0 && (force || !isInternalNavRef.current)) {
                    // 使用 setTimeout 确保 DOM 已渲染
                    const restore = () => {
                        window.scrollTo(0, savedY)
                    }

                    // 多重恢复策略：立即、下一帧、延迟
                    restore()
                    requestAnimationFrame(restore)
                    setTimeout(restore, 100)
                    setTimeout(restore, 500)
                }
                // 重置内部导航标志
                isInternalNavRef.current = false
            } catch (e) {
                // 忽略恢复错误
            }
        }

        // Hook 系统内导航
        const originalPushState = history.pushState
        const originalReplaceState = history.replaceState

        history.pushState = function (...args) {
            saveScroll()
            return originalPushState.apply(this, args)
        }

        history.replaceState = function (...args) {
            saveScroll()
            return originalReplaceState.apply(this, args)
        }

        // 监听各种离开事件
        const events = ['beforeunload', 'pagehide']
        events.forEach(event => {
            window.addEventListener(event, saveScroll, { capture: true })
        })

        // 监听可见性变化
        const handleVisibilityChange = () => {
            if (document.visibilityState === 'hidden') {
                saveScroll()
            }
        }
        document.addEventListener('visibilitychange', handleVisibilityChange)

        // 监听链接点击
        const handleClick = (e: Event) => {
            const target = e.target as HTMLElement
            const link = target.closest('a')
            if (link && link.href && !link.href.includes('#')) {
                saveScroll()
            }
        }
        document.addEventListener('click', handleClick, true)

        // 监听返回事件
        const handlePopState = () => {
            // 浏览器返回时强制恢复滚动位置
            setTimeout(() => restoreScroll(true), 0)
        }
        window.addEventListener('popstate', handlePopState)

        // 页面显示时恢复
        const handlePageShow = () => {
            restoreScroll()
        }
        window.addEventListener('pageshow', handlePageShow)

        // 组件挂载时恢复
        restoreScroll()

            // 暴露标记内部导航的方法到全局
            ; (window as any).__markInternalNav = () => {
                isInternalNavRef.current = true
            }

        // 清理函数
        return () => {
            // 恢复原始方法
            history.pushState = originalPushState
            history.replaceState = originalReplaceState

            // 移除事件监听
            events.forEach(event => {
                window.removeEventListener(event, saveScroll, { capture: true })
            })
            document.removeEventListener('visibilitychange', handleVisibilityChange)
            document.removeEventListener('click', handleClick, true)
            window.removeEventListener('popstate', handlePopState)
            window.removeEventListener('pageshow', handlePageShow)
        }
    }, [location.pathname, location.search])
}