from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from collections import defaultdict, Counter
from dataclasses import dataclass


def categorize_test_by_name(test_name: str) -> Dict[str, str]:
    """根据测试用例名称推断测试类别和功能域"""
    categories = {
        "component": "未知组件",
        "operation": "未知操作",
        "domain": "未知域"
    }

    # 常见的测试组件模式
    component_patterns = {
        "hyp": "虚拟化管理器",
        "vm": "虚拟机",
        "vcpu": "虚拟CPU",
        "memory": "内存管理",
        "mem": "内存管理",
        "addr": "地址管理",
        "phys": "物理内存",
        "virt": "虚拟内存",
        "page": "页面管理",
        "chunk": "内存块",
        "refcount": "引用计数",
        "ftrace": "函数跟踪",
        "event": "事件处理",
        "buffer": "缓冲区管理",
        "rb": "环形缓冲区",
        "sve": "可扩展向量扩展",
        "nv": "嵌套虚拟化",
        "pkvm": "受保护KVM"
    }

    # 常见的操作模式
    operation_patterns = {
        "basic": "基础功能",
        "set": "设置操作",
        "get": "获取操作",
        "enable": "启用操作",
        "disable": "禁用操作",
        "increment": "递增操作",
        "decrement": "递减操作",
        "alignment": "对齐检查",
        "arithmetic": "算术运算",
        "comparison": "比较操作",
        "assign": "赋值操作",
        "boundary": "边界条件",
        "edge": "边缘情况",
        "null": "空指针处理",
        "range": "范围验证",
        "error": "错误处理",
        "reset": "重置操作",
        "calculation": "计算逻辑"
    }

    # 分析测试名称
    test_lower = test_name.lower()

    # 识别组件
    for pattern, component in component_patterns.items():
        if pattern in test_lower:
            categories["component"] = component
            break

    # 识别操作类型
    for pattern, operation in operation_patterns.items():
        if pattern in test_lower:
            categories["operation"] = operation
            break

    # 识别功能域
    if any(x in test_lower for x in ["memory", "mem", "addr", "phys", "virt", "page", "chunk"]):
        categories["domain"] = "内存管理"
    elif any(x in test_lower for x in ["hyp", "vm", "vcpu", "pkvm"]):
        categories["domain"] = "虚拟化"
    elif any(x in test_lower for x in ["trace", "event", "buffer"]):
        categories["domain"] = "跟踪事件"
    elif any(x in test_lower for x in ["sve", "vector"]):
        categories["domain"] = "向量处理"
    elif any(x in test_lower for x in ["refcount", "atomic"]):
        categories["domain"] = "同步机制"

    return categories


def analyze_failure_patterns(failed_tests: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分析失败测试的模式和特征"""
    if not failed_tests:
        return {"pattern_analysis": "no_failures"}

    # 按组件分类失败
    component_failures = defaultdict(list)
    operation_failures = defaultdict(list)
    domain_failures = defaultdict(list)

    for test in failed_tests:
        test_name = test.get("case", "")
        categories = categorize_test_by_name(test_name)

        component_failures[categories["component"]].append(test_name)
        operation_failures[categories["operation"]].append(test_name)
        domain_failures[categories["domain"]].append(test_name)

    # 分析失败模式
    analysis = {
        "total_failures": len(failed_tests),
        "component_breakdown": dict(component_failures),
        "operation_breakdown": dict(operation_failures),
        "domain_breakdown": dict(domain_failures),
        "failure_patterns": []
    }

    # 识别集中失败模式
    if len(component_failures) == 1:
        component = list(component_failures.keys())[0]
        analysis["failure_patterns"].append(f"所有失败集中在{component}组件")

    if len(domain_failures) == 1:
        domain = list(domain_failures.keys())[0]
        analysis["failure_patterns"].append(f"所有失败集中在{domain}功能域")

    # 检查是否有特定操作类型的集中失败
    for operation, tests in operation_failures.items():
        if len(tests) >= len(failed_tests) * 0.5:  # 超过50%的失败
            analysis["failure_patterns"].append(f"大量{operation}操作失败")

    return analysis


def generate_unit_test_root_causes(
    failed_tests: List[Dict[str, Any]],
    pattern_analysis: Dict[str, Any],
    test_summary: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """基于失败模式生成可能的根因分析"""
    root_causes = []

    if not failed_tests:
        return root_causes

    failure_rate = (test_summary.get("failed", 0) /
                    max(test_summary.get("total", 1), 1)) * 100

    # 基于失败率的根因分析
    if failure_rate >= 50:
        root_causes.append({
            "cause": "系统性问题：超过50%的测试失败，可能存在基础环境或内核配置问题",
            "likelihood": 0.9,
            "category": "systemic_issue"
        })
    elif failure_rate >= 20:
        root_causes.append({
            "cause": "部分系统问题：20-50%的测试失败，可能存在特定子系统问题",
            "likelihood": 0.7,
            "category": "subsystem_issue"
        })

    # 基于组件分析的根因
    component_breakdown = pattern_analysis.get("component_breakdown", {})
    for component, tests in component_breakdown.items():
        if component != "unknown" and len(tests) >= 2:
            if component == "hypervisor":
                root_causes.append({
                    "cause": f"Hypervisor相关功能异常：{len(tests)}个hypervisor测试失败，可能是EL2权限或虚拟化配置问题",
                    "likelihood": 0.8,
                    "category": "hypervisor_issue"
                })
            elif component == "memory_management":
                root_causes.append({
                    "cause": f"内存管理异常：{len(tests)}个内存相关测试失败，可能是页表配置或内存分配问题",
                    "likelihood": 0.8,
                    "category": "memory_issue"
                })
            elif component == "virtual_machine":
                root_causes.append({
                    "cause": f"虚拟机功能异常：{len(tests)}个VM测试失败，可能是虚拟化环境配置问题",
                    "likelihood": 0.7,
                    "category": "vm_issue"
                })

    # 基于功能域分析的根因
    domain_breakdown = pattern_analysis.get("domain_breakdown", {})
    for domain, tests in domain_breakdown.items():
        if domain != "unknown" and len(tests) >= 2:
            if domain == "memory_management":
                root_causes.append({
                    "cause": f"内存管理子系统问题：{len(tests)}个内存管理测试失败，检查内存配置和页表设置",
                    "likelihood": 0.8,
                    "category": "memory_subsystem"
                })
            elif domain == "virtualization":
                root_causes.append({
                    "cause": f"虚拟化子系统问题：{len(tests)}个虚拟化测试失败，检查pKVM配置和EL1/EL2权限设置",
                    "likelihood": 0.8,
                    "category": "virtualization_subsystem"
                })

    # 基于操作类型的根因分析
    operation_breakdown = pattern_analysis.get("operation_breakdown", {})
    for operation, tests in operation_breakdown.items():
        if operation != "unknown" and len(tests) >= 2:
            if operation == "null_pointer_handling":
                root_causes.append({
                    "cause": f"空指针处理异常：{len(tests)}个空指针测试失败，可能存在内存访问保护问题",
                    "likelihood": 0.9,
                    "category": "null_pointer_issue"
                })
            elif operation == "boundary_condition":
                root_causes.append({
                    "cause": f"边界条件处理异常：{len(tests)}个边界测试失败，可能存在参数验证或范围检查问题",
                    "likelihood": 0.8,
                    "category": "boundary_issue"
                })

    # 如果没有明显的模式，提供通用根因
    if not root_causes:
        root_causes.append({
            "cause": "零散测试失败：失败的测试用例没有明显的共同模式，可能是独立的代码缺陷",
            "likelihood": 0.6,
            "category": "isolated_failures"
        })

    return root_causes


def generate_unit_test_suggestions(
    failed_tests: List[Dict[str, Any]],
    root_causes: List[Dict[str, Any]]
) -> List[str]:
    """基于失败测试和根因分析生成具体的检查建议"""
    suggestions = []

    if not failed_tests:
        return ["所有单元测试通过，无需额外检查"]

    # 基于根因类别生成建议
    cause_categories = {rc.get("category", "") for rc in root_causes}

    if "systemic_issue" in cause_categories:
        suggestions.extend([
            "检查内核启动参数和配置选项",
            "验证pKVM是否正确初始化：dmesg | grep -i pkvm",
            "检查系统资源限制：ulimit -a",
            "验证内核模块加载状态：lsmod | grep kvm"
        ])

    if "hypervisor_issue" in cause_categories or "virtualization_subsystem" in cause_categories:
        suggestions.extend([
            "检查EL2权限设置：cat /proc/cpuinfo | grep Features",
            "验证虚拟化扩展支持：grep -i virtualization /proc/cpuinfo",
            "检查pKVM初始化日志：dmesg | grep -E '(pkvm|hyp|el2)'",
            "验证hypervisor内存映射：cat /proc/iomem | grep hyp"
        ])

    if "memory_issue" in cause_categories or "memory_subsystem" in cause_categories:
        suggestions.extend([
            "检查内存配置：cat /proc/meminfo",
            "验证页表配置：cat /proc/pagetypeinfo",
            "检查内存分配器状态：cat /proc/slabinfo | head -20",
            "查看内存相关内核日志：dmesg | grep -E '(memory|oom|page)'"
        ])

    if "null_pointer_issue" in cause_categories:
        suggestions.extend([
            "检查内核空指针保护：cat /proc/sys/kernel/kptr_restrict",
            "验证内存访问保护：dmesg | grep -i 'protection\\|fault'",
            "检查KASLR状态：cat /proc/cmdline | grep kaslr"
        ])

    if "boundary_issue" in cause_categories:
        suggestions.extend([
            "检查内核参数验证配置：cat /proc/sys/kernel/panic_on_oops",
            "验证调试选项：cat /proc/config.gz | zcat | grep -E 'DEBUG|KASAN|UBSAN'",
            "检查边界检查相关日志：dmesg | grep -E '(bounds|overflow|underflow)'"
        ])

    # 通用建议
    suggestions.extend([
        f"重新运行失败的测试用例：{', '.join([t.get('case', '') for t in failed_tests[:3]])}",
        "检查测试环境一致性：确保与之前成功运行时的环境配置相同",
        "查看完整的单元测试日志以获取更多错误详情"
    ])

    # 去重并限制数量
    unique_suggestions = list(dict.fromkeys(suggestions))
    return unique_suggestions[:8]  # 最多返回8个建议


def analyze_unit_test_anomalies(
    records: List[Dict[str, Any]],
    test_summary: Dict[str, Any],
    k2_client=None
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """分析单元测试异常，生成AI分析结果"""
    anomalies = []

    # 提取失败的测试用例
    failed_tests = [r for r in records if r.get(
        "status") == "FAIL" and r.get("case")]

    if not failed_tests:
        # 没有失败的测试用例，返回空异常列表
        return anomalies, {"ai_analysis_success": False}

    # 分析失败模式
    pattern_analysis = analyze_failure_patterns(failed_tests)

    # 生成根因分析
    root_causes = []
    ai_analysis_success = False

    if k2_client and k2_client.enabled():
        try:
            # 尝试使用AI增强分析
            root_causes = generate_ai_enhanced_root_causes(
                failed_tests, pattern_analysis, test_summary, k2_client)
            ai_analysis_success = True
        except Exception as e:
            print(f"AI分析失败，降级到规则分析: {e}")
            # AI分析失败，降级到基于规则的分析
            root_causes = generate_unit_test_root_causes(
                failed_tests, pattern_analysis, test_summary)
    else:
        # 使用基于规则的分析
        root_causes = generate_unit_test_root_causes(
            failed_tests, pattern_analysis, test_summary)

    # 生成检查建议
    suggestions = generate_unit_test_suggestions(failed_tests, root_causes)

    # 为每个失败的测试用例创建异常记录
    for failed_test in failed_tests:
        test_name = failed_test.get("case", "")
        categories = categorize_test_by_name(test_name)

        # 确定严重程度
        severity = "medium"  # 默认中等
        confidence = 0.8

        # 根据失败模式调整严重程度
        if len(failed_tests) >= test_summary.get("total", 1) * 0.5:
            severity = "high"
            confidence = 0.9
        elif categories["operation"] in ["空指针处理", "边界条件"]:
            severity = "high"
            confidence = 0.85
        elif categories["domain"] in ["内存管理", "虚拟化"]:
            severity = "medium"
            confidence = 0.8
        else:
            severity = "low"
            confidence = 0.7

        anomaly = {
            "suite": "UnitTest",
            "case": test_name,
            "metric": "test_result",
            "current_value": 0,  # 失败 = 0
            "severity": severity,
            "confidence": confidence,
            "primary_reason": f"单元测试失败：{test_name} 在 {categories['domain']} 功能域的 {categories['operation']} 操作中失败",
            "supporting_evidence": {
                "history_n": 1,  # 当前只有一次测试结果
                "test_category": categories,
                "failure_pattern": pattern_analysis,
                "total_failures": len(failed_tests),
                "failure_rate": (len(failed_tests) / max(test_summary.get("total", 1), 1)) * 100
            },
            "root_causes": root_causes,
            "suggested_next_checks": suggestions
        }

        anomalies.append(anomaly)

    return anomalies, {"ai_analysis_success": ai_analysis_success}


# ========== 代码分析接口（预留给未来集成） ==========

@dataclass
class TestCodeContext:
    """测试代码上下文信息"""
    test_name: str
    test_code: str  # 测试函数代码
    target_function_code: Optional[str] = None  # 被测试的原始函数代码
    file_path: Optional[str] = None  # 文件路径
    line_number: Optional[int] = None  # 失败的行号
    error_message: Optional[str] = None  # 错误消息
    stack_trace: Optional[str] = None  # 堆栈跟踪


def analyze_test_with_code_context(
    test_name: str,
    test_result: str,  # "PASS" or "FAIL"
    code_context: Optional[TestCodeContext] = None
) -> Dict[str, Any]:
    """
    使用代码上下文分析单元测试失败的根因

    这是一个预留接口，用于未来与其他平台集成，
    当能够获取测试代码和被测函数代码时，进行更深入的分析。

    Args:
        test_name: 测试用例名称
        test_result: 测试结果 (PASS/FAIL)
        code_context: 代码上下文信息（可选）

    Returns:
        包含详细分析结果的字典
    """
    analysis = {
        "test_name": test_name,
        "result": test_result,
        "has_code_context": code_context is not None,
        "analysis_type": "code_based" if code_context else "name_based",
        "root_causes": [],
        "suggestions": [],
        "code_insights": {}
    }

    if test_result == "PASS":
        analysis["summary"] = "测试通过，无需分析"
        return analysis

    # 基于名称的基础分析
    categories = categorize_test_by_name(test_name)
    analysis["test_categories"] = categories

    if code_context:
        # 有代码上下文时的深度分析
        analysis["code_insights"] = analyze_code_patterns(code_context)
        analysis["root_causes"] = generate_code_based_root_causes(
            code_context, categories)
        analysis["suggestions"] = generate_code_based_suggestions(
            code_context, categories)
    else:
        # 仅基于名称的分析
        analysis["root_causes"] = generate_name_based_root_causes(
            test_name, categories)
        analysis["suggestions"] = generate_name_based_suggestions(
            test_name, categories)

    return analysis


def analyze_code_patterns(code_context: TestCodeContext) -> Dict[str, Any]:
    """
    分析代码模式，识别潜在问题

    未来可以集成更复杂的代码分析，如：
    - AST分析
    - 静态代码分析
    - 模式匹配
    - AI代码理解
    """
    insights = {
        "has_test_code": bool(code_context.test_code),
        "has_target_code": bool(code_context.target_function_code),
        "has_error_message": bool(code_context.error_message),
        "has_stack_trace": bool(code_context.stack_trace)
    }

    if code_context.test_code:
        # 简单的代码模式分析
        test_code_lower = code_context.test_code.lower()
        insights["patterns"] = {
            "uses_assertions": "assert" in test_code_lower,
            "has_null_checks": "null" in test_code_lower or "none" in test_code_lower,
            "has_boundary_checks": any(x in test_code_lower for x in ["<", ">", "<=", ">=", "boundary", "limit"]),
            "has_memory_operations": any(x in test_code_lower for x in ["malloc", "free", "alloc", "dealloc", "memcpy"]),
            "has_error_handling": any(x in test_code_lower for x in ["try", "catch", "except", "error", "fail"])
        }

    if code_context.error_message:
        # 分析错误消息
        error_lower = code_context.error_message.lower()
        insights["error_type"] = {
            "is_assertion_error": "assert" in error_lower,
            "is_null_pointer": "null" in error_lower or "nullptr" in error_lower,
            "is_memory_error": any(x in error_lower for x in ["segfault", "memory", "heap", "stack"]),
            "is_type_error": "type" in error_lower,
            "is_value_error": "value" in error_lower or "invalid" in error_lower
        }

    return insights


def generate_code_based_root_causes(
    code_context: TestCodeContext,
    categories: Dict[str, str]
) -> List[Dict[str, Any]]:
    """基于代码上下文生成根因分析"""
    root_causes = []

    if code_context.error_message:
        # 基于错误消息的根因分析
        error_lower = code_context.error_message.lower()

        if "assert" in error_lower:
            root_causes.append({
                "cause": f"断言失败：测试中的某个断言条件未满足",
                "likelihood": 0.9,
                "evidence": code_context.error_message[:200] if code_context.error_message else None
            })

        if "null" in error_lower or "nullptr" in error_lower:
            root_causes.append({
                "cause": "空指针异常：代码尝试访问空指针或未初始化的内存",
                "likelihood": 0.95,
                "evidence": code_context.error_message[:200] if code_context.error_message else None
            })

        if any(x in error_lower for x in ["segfault", "segmentation"]):
            root_causes.append({
                "cause": "段错误：内存访问违规，可能是越界访问或使用已释放的内存",
                "likelihood": 0.95,
                "evidence": code_context.error_message[:200] if code_context.error_message else None
            })

    if code_context.test_code and code_context.target_function_code:
        # 基于代码对比的根因分析
        root_causes.append({
            "cause": "测试与实现不匹配：测试期望的行为与函数实际实现存在差异",
            "likelihood": 0.7,
            "evidence": "代码分析显示测试期望与实现存在偏差"
        })

    # 如果没有找到特定的根因，提供通用分析
    if not root_causes:
        root_causes.append({
            "cause": f"测试失败在{categories.get('domain', '未知')}域的{categories.get('operation', '未知')}操作",
            "likelihood": 0.6,
            "evidence": "基于测试名称和类别分析"
        })

    return root_causes


def generate_code_based_suggestions(
    code_context: TestCodeContext,
    categories: Dict[str, str]
) -> List[str]:
    """基于代码上下文生成调试建议"""
    suggestions = []

    # 基于错误类型的建议
    if code_context.error_message:
        error_lower = code_context.error_message.lower()

        if "assert" in error_lower:
            suggestions.extend([
                "检查断言条件的逻辑是否正确",
                "验证测试输入数据是否符合预期",
                "使用调试器在断言失败处设置断点"
            ])

        if "null" in error_lower:
            suggestions.extend([
                "检查指针初始化逻辑",
                "添加空指针检查保护",
                "验证内存分配是否成功"
            ])

        if "memory" in error_lower:
            suggestions.extend([
                "使用内存检查工具（如Valgrind）分析",
                "检查内存分配和释放的配对",
                "验证数组边界访问"
            ])

    # 基于代码上下文的建议
    if code_context.file_path:
        suggestions.append(f"检查源文件：{code_context.file_path}")

    if code_context.line_number:
        suggestions.append(f"重点调试第{code_context.line_number}行附近的代码")

    if code_context.stack_trace:
        suggestions.append("分析堆栈跟踪以定位问题源头")

    # 通用建议
    suggestions.extend([
        f"在{categories.get('component', '相关')}组件中添加日志输出",
        "对比成功和失败的测试用例，找出差异",
        "检查最近的代码变更是否影响了该功能"
    ])

    return suggestions[:8]  # 限制建议数量


def generate_name_based_root_causes(
    test_name: str,
    categories: Dict[str, str]
) -> List[Dict[str, Any]]:
    """仅基于测试名称生成根因分析（无代码上下文时）"""
    root_causes = []

    # 基于测试名称模式的分析
    test_lower = test_name.lower()

    if "assign" in test_lower or "assignment" in test_lower:
        root_causes.append({
            "cause": "赋值操作异常：可能是赋值逻辑错误或类型不匹配",
            "likelihood": 0.7,
            "evidence": f"测试名称包含'assign'关键字"
        })

    if "null" in test_lower or "nullptr" in test_lower:
        root_causes.append({
            "cause": "空指针处理问题：空指针检查或处理逻辑可能存在缺陷",
            "likelihood": 0.8,
            "evidence": f"测试名称包含'null'关键字"
        })

    if "boundary" in test_lower or "edge" in test_lower:
        root_causes.append({
            "cause": "边界条件处理异常：边界值或极端情况处理不当",
            "likelihood": 0.75,
            "evidence": f"测试名称包含边界相关关键字"
        })

    # 基于组件和域的通用分析
    component = categories.get("component", "unknown")
    domain = categories.get("domain", "unknown")

    if component != "unknown":
        root_causes.append({
            "cause": f"{component}组件功能异常：该组件的核心功能可能存在缺陷",
            "likelihood": 0.6,
            "evidence": f"基于组件分类：{component}"
        })

    return root_causes


def generate_name_based_suggestions(
    test_name: str,
    categories: Dict[str, str]
) -> List[str]:
    """仅基于测试名称生成调试建议（无代码上下文时）"""
    suggestions = []

    component = categories.get("component", "unknown")
    operation = categories.get("operation", "unknown")
    domain = categories.get("domain", "unknown")

    # 基于组件的建议
    if component == "hypervisor":
        suggestions.extend([
            "检查hypervisor初始化状态",
            "验证EL2权限配置",
            "查看hypervisor相关的内核日志"
        ])
    elif component == "memory_management":
        suggestions.extend([
            "检查内存分配策略",
            "验证页表配置",
            "使用内存调试工具分析"
        ])

    # 基于操作类型的建议
    if operation == "赋值操作":
        suggestions.extend([
            "检查赋值操作的类型兼容性",
            "验证赋值前后的值是否正确",
            "检查是否有内存对齐问题"
        ])

    # 通用建议
    suggestions.extend([
        f"查看{test_name}测试的源代码",
        f"在{domain}相关代码中添加调试日志",
        "运行相关的单元测试套件以找出模式",
        "检查测试环境配置是否正确"
    ])

    return suggestions[:8]


# ========== AI增强分析接口（预留） ==========

async def analyze_with_ai_model(
    test_failures: List[Dict[str, Any]],
    code_contexts: Optional[List[TestCodeContext]] = None,
    model_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    使用AI模型进行深度分析（异步接口）

    这是一个预留的异步接口，用于未来集成大语言模型进行更智能的分析。
    可以将测试失败信息和代码上下文发送给AI模型，获取更精确的根因分析。

    Args:
        test_failures: 失败的测试列表
        code_contexts: 代码上下文列表（可选）
        model_config: AI模型配置（可选）

    Returns:
        AI分析结果
    """
    # 预留接口实现
    # 未来可以在这里调用OpenAI、Claude等模型API
    # 或者使用本地部署的代码分析模型

    return {
        "status": "not_implemented",
        "message": "AI增强分析接口预留，待未来实现",
        "test_count": len(test_failures),
        "has_code_context": code_contexts is not None
    }


def generate_ai_enhanced_root_causes(
    failed_tests: List[Dict[str, Any]],
    pattern_analysis: Dict[str, Any],
    test_summary: Dict[str, Any],
    k2_client
) -> List[Dict[str, Any]]:
    """
    使用AI增强的根因分析

    当前基于测试用例名称进行AI分析，未来会扩展到包含代码上下文
    """
    try:
        # 准备AI分析的输入数据
        test_names = [test.get("case", "") for test in failed_tests]
        failure_rate = (test_summary.get("failed", 0) /
                        max(test_summary.get("total", 1), 1)) * 100

        # 构建AI分析提示
        prompt = f"""
分析以下单元测试失败情况：

失败的测试用例：
{', '.join(test_names)}

失败统计：
- 总测试数：{test_summary.get("total", 0)}
- 失败数：{test_summary.get("failed", 0)}
- 失败率：{failure_rate:.1f}%

模式分析：
{pattern_analysis.get("failure_patterns", [])}

请基于测试用例名称分析可能的根本原因，并提供具体的修复建议。
返回JSON格式，包含cause（原因）、likelihood（可能性0-1）、category（类别）字段。
"""

        # 调用AI模型进行真正的AI分析
        ai_response = _call_ai_for_unit_test_analysis(
            k2_client, prompt, test_names)

        print(f"AI分析响应: {ai_response}")

        if ai_response and "root_causes" in ai_response:
            print(f"使用AI分析结果: {ai_response['root_causes']}")
            return ai_response["root_causes"]
        else:
            print(f"AI响应格式不正确或为空: {ai_response}")
            raise Exception("AI分析未返回有效的root_causes")

    except Exception as e:
        # AI分析失败时回退到规则分析
        print(f"AI分析失败，回退到规则分析: {e}")

    # 回退到基于规则的分析
    return generate_unit_test_root_causes(failed_tests, pattern_analysis, test_summary)


def _call_ai_for_unit_test_analysis(k2_client, prompt: str, test_names: List[str]) -> Dict[str, Any]:
    """
    调用AI模型进行单元测试分析

    真正调用AI大模型进行分析，基于测试用例名称和失败模式
    """
    try:
        # 直接调用AI模型，不使用K2Client的标准格式
        # 因为K2Client是为性能测试设计的，我们需要直接调用模型

        # 获取可用的模型
        available_models = [
            m for m in k2_client.models if m.enabled and m.error_count < 5]
        if not available_models:
            raise Exception("没有可用的AI模型")

        # 选择优先级最高的模型
        available_models.sort(key=lambda x: x.priority)
        model = available_models[0]

        print(f"正在调用AI模型 {model.name} 分析单元测试失败: {test_names}")

        # 构建AI请求
        url = model.api_base.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}

        # 仅在有有效API_KEY时才添加Authorization头
        if model.api_key and model.api_key.strip() and model.api_key.upper() != "EMPTY":
            headers["Authorization"] = f"Bearer {model.api_key}"

        # 构建单元测试专用的提示词
        system_prompt = """你是一名内核单元测试分析专家。你将收到失败的单元测试用例信息，需要基于测试用例名称和失败模式进行根因分析。

任务：识别单元测试失败的真正原因，并给出最可能的根因和具体的后续检查建议。

准则：
- 测试分类：根据测试用例名称推断测试的功能域（内存管理、虚拟化、跟踪事件、向量处理、同步机制等）和操作类型（基础功能、设置操作、获取操作、边界条件、错误处理等）。
- 严重度评估：基于失败测试的功能重要性和影响范围确定严重度：高严重度（核心功能、内存安全、系统稳定性）、中等严重度（功能性错误、边界条件）、低严重度（边缘情况、非关键路径）。
- 根因分析：每个失败测试必须给出 primary_reason 与至少一个 root_cause（含 likelihood 0~1），基于测试名称模式、功能域特征和常见失败原因进行推断。
- 后续建议：每个异常必须在 suggested_next_checks 中提供3-5个具体可执行的检查建议，例如：『检查内核日志（dmesg）中是否存在相关错误信息』、『审查测试用例的具体实现代码』、『验证相关内核模块的加载状态』、『检查系统配置是否满足测试前提条件』、『运行相关的回归测试套件』等。
- 置信度：每个异常项必须包含 confidence 字段（0~1之间的数值），基于测试名称的明确性和失败模式的典型性评估。
- 环境：目标平台为 ARM64，Linux 内核 pKVM 场景（EL1/EL2）。常见单元测试失败原因包括：内存管理错误（页表配置、地址映射、内存分配）、虚拟化功能异常（EL2权限、hypervisor状态、VCPU管理）、同步机制问题（原子操作、引用计数、锁机制）、向量处理错误（SVE配置、寄存器状态）、跟踪功能异常（ftrace配置、事件处理、缓冲区管理）、边界条件处理（空指针、范围检查、溢出保护）等。
- 模式识别：基于测试名称中的关键字（如 basic、boundary、edge、null、error、enable、disable、set、get 等）推断测试意图和可能的失败原因。
- 语言：除专有名词外，所有自然语言字段请使用中文表达（含 primary_reason、root_causes.cause、suggested_next_checks 等）。
- 输出：confidence 返回 0~1 的小数；严格按 JSON 输出，符合给定 schema，不要输出 Markdown 或解释文字。

JSON输出格式：
{
    "anomalies": [
        {
            "suite": "UnitTest",
            "case": "测试用例名",
            "metric": "test_result",
            "severity": "high|medium|low",
            "confidence": 0.0-1.0,
            "primary_reason": "主要原因描述",
            "supporting_evidence": {},
            "root_causes": [
                {
                    "cause": "具体根因",
                    "likelihood": 0.0-1.0
                }
            ],
            "suggested_next_checks": ["检查步骤1", "检查步骤2", "检查步骤3"]
        }
    ]
}"""

        user_content = f"""请分析以下失败的单元测试用例：

{prompt}

失败的测试用例：{', '.join(test_names)}

请基于测试用例名称和失败模式，分析可能的根本原因并提供具体的修复建议。"""

        data = {
            "model": model.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.2,
        }

        # 发送请求
        import requests
        resp = requests.post(url, headers=headers, json=data,
                             timeout=model.timeout, verify=True)
        resp.raise_for_status()

        # 解析响应
        js = resp.json()
        content = js["choices"][0]["message"]["content"]

        print(f"AI模型原始响应: {content}")

        # 解析JSON响应
        from ia.analyzer.k2_client import coerce_json_from_text
        ai_result = coerce_json_from_text(content)

        print(f"解析后的AI结果: {ai_result}")

        # 转换为我们需要的格式
        if ai_result and "anomalies" in ai_result:
            root_causes = []
            for anomaly in ai_result["anomalies"]:
                # 从AI结果中提取根因
                ai_root_causes = anomaly.get("root_causes", [])
                if ai_root_causes:
                    for ai_cause in ai_root_causes:
                        root_cause = {
                            "cause": ai_cause.get("cause", anomaly.get("primary_reason", "AI分析的根因")),
                            "likelihood": ai_cause.get("likelihood", anomaly.get("confidence", 0.8)),
                            "category": "AI分析",
                            "ai_enhanced": True,
                            "ai_details": {
                                "severity": anomaly.get("severity", "medium"),
                                "supporting_evidence": anomaly.get("supporting_evidence", {}),
                                "suggested_checks": anomaly.get("suggested_next_checks", [])
                            }
                        }
                        root_causes.append(root_cause)
                else:
                    # 如果没有具体的root_causes，使用primary_reason
                    root_cause = {
                        "cause": anomaly.get("primary_reason", "AI分析的根因"),
                        "likelihood": anomaly.get("confidence", 0.8),
                        "category": "AI分析",
                        "ai_enhanced": True,
                        "ai_details": {
                            "severity": anomaly.get("severity", "medium"),
                            "supporting_evidence": anomaly.get("supporting_evidence", {}),
                            "suggested_checks": anomaly.get("suggested_next_checks", [])
                        }
                    }
                    root_causes.append(root_cause)

            # 更新模型统计
            model.success_count += 1
            model.error_count = max(0, model.error_count - 1)

            return {"root_causes": root_causes}
        else:
            raise Exception("AI模型未返回有效的分析结果")

    except Exception as e:
        print(f"AI模型调用失败: {e}")
        # 更新模型错误计数
        if 'model' in locals():
            model.error_count += 1
        # 重新抛出异常，让上层处理降级
        raise e
