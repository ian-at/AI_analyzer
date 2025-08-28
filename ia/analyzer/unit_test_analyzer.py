from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from collections import defaultdict, Counter
from dataclasses import dataclass


def categorize_test_by_name(test_name: str) -> Dict[str, str]:
    """根据测试用例名称推断测试类别和功能域"""
    categories = {
        "component": "unknown",
        "operation": "unknown",
        "domain": "unknown"
    }

    # 常见的测试组件模式
    component_patterns = {
        "hyp": "hypervisor",
        "vm": "virtual_machine",
        "vcpu": "virtual_cpu",
        "memory": "memory_management",
        "mem": "memory_management",
        "addr": "address_management",
        "phys": "physical_memory",
        "virt": "virtual_memory",
        "page": "page_management",
        "chunk": "memory_chunk",
        "refcount": "reference_counting",
        "ftrace": "function_tracing",
        "event": "event_handling",
        "buffer": "buffer_management",
        "rb": "ring_buffer",
        "sve": "scalable_vector_extension",
        "nv": "nested_virtualization",
        "pkvm": "protected_kvm"
    }

    # 常见的操作模式
    operation_patterns = {
        "basic": "basic_functionality",
        "set": "setter_operation",
        "get": "getter_operation",
        "enable": "enable_operation",
        "disable": "disable_operation",
        "increment": "increment_operation",
        "decrement": "decrement_operation",
        "alignment": "alignment_check",
        "arithmetic": "arithmetic_operation",
        "comparison": "comparison_operation",
        "assign": "assignment_operation",
        "boundary": "boundary_condition",
        "edge": "edge_case",
        "null": "null_pointer_handling",
        "range": "range_validation",
        "error": "error_handling",
        "reset": "reset_operation",
        "calculation": "calculation_logic"
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
        categories["domain"] = "memory_management"
    elif any(x in test_lower for x in ["hyp", "vm", "vcpu", "pkvm"]):
        categories["domain"] = "virtualization"
    elif any(x in test_lower for x in ["trace", "event", "buffer"]):
        categories["domain"] = "tracing_events"
    elif any(x in test_lower for x in ["sve", "vector"]):
        categories["domain"] = "vector_processing"
    elif any(x in test_lower for x in ["refcount", "atomic"]):
        categories["domain"] = "synchronization"

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
    test_summary: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """分析单元测试异常，生成AI分析结果"""
    anomalies = []

    # 提取失败的测试用例
    failed_tests = [r for r in records if r.get(
        "status") == "FAIL" and r.get("case")]

    if not failed_tests:
        # 没有失败的测试用例，返回空异常列表
        return anomalies

    # 分析失败模式
    pattern_analysis = analyze_failure_patterns(failed_tests)

    # 生成根因分析
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
        elif categories["operation"] in ["null_pointer_handling", "boundary_condition"]:
            severity = "high"
            confidence = 0.85
        elif categories["domain"] in ["memory_management", "virtualization"]:
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

    return anomalies


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
    if operation == "assignment_operation":
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
