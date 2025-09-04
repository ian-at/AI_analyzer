from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from collections import defaultdict, Counter
from dataclasses import dataclass

from .unit_test_analyzer import categorize_test_by_name  # 复用单元测试的分类逻辑


def analyze_interface_failure_patterns(failed_tests: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分析接口测试失败模式"""
    if not failed_tests:
        return {"failure_patterns": [], "component_breakdown": {}, "operation_breakdown": {}}

    # 基于测试名称的模式分析
    failure_patterns = []
    component_breakdown = defaultdict(list)
    operation_breakdown = defaultdict(list)

    # 接口测试特有的分类模式
    api_category_breakdown = defaultdict(list)
    severity_breakdown = defaultdict(list)

    for test in failed_tests:
        test_name = test.get("case", "")
        fail_reason = test.get("raw", {}).get("fail_reason", "")

        # 分析测试名称中的关键词
        test_name_lower = test_name.lower()

        # API类别分析
        if "api_version" in test_name_lower:
            api_category_breakdown["api_version"].append(test)
        elif "extension" in test_name_lower or "capability" in test_name_lower:
            api_category_breakdown["capability_check"].append(test)
        elif "preferred_target" in test_name_lower:
            api_category_breakdown["target_config"].append(test)
        elif "basic" in test_name_lower:
            api_category_breakdown["basic_interface"].append(test)
        elif "invalid" in test_name_lower or "error" in test_name_lower:
            api_category_breakdown["error_handling"].append(test)
        else:
            api_category_breakdown["other"].append(test)

        # 基于失败原因的严重程度分析
        if fail_reason:
            fail_reason_lower = fail_reason.lower()
            if any(keyword in fail_reason_lower for keyword in ["crash", "panic", "segfault"]):
                severity_breakdown["critical"].append(test)
            elif any(keyword in fail_reason_lower for keyword in ["not equal", "mismatch", "should"]):
                severity_breakdown["assertion_failure"].append(test)
            elif any(keyword in fail_reason_lower for keyword in ["timeout", "slow"]):
                severity_breakdown["performance"].append(test)
            else:
                severity_breakdown["functional"].append(test)

        # 复用单元测试的组件分析逻辑
        categories = categorize_test_by_name(test_name)
        component = categories.get("component", "unknown")
        operation = categories.get("operation", "unknown")

        component_breakdown[component].append(test)
        operation_breakdown[operation].append(test)

    # 生成失败模式描述
    for api_cat, tests in api_category_breakdown.items():
        if len(tests) >= 2:
            failure_patterns.append(f"{len(tests)}个{api_cat}相关测试失败")

    for severity, tests in severity_breakdown.items():
        if len(tests) >= 2:
            failure_patterns.append(f"{len(tests)}个{severity}级别失败")

    return {
        "failure_patterns": failure_patterns,
        "component_breakdown": dict(component_breakdown),
        "operation_breakdown": dict(operation_breakdown),
        "api_category_breakdown": dict(api_category_breakdown),
        "severity_breakdown": dict(severity_breakdown)
    }


def generate_interface_test_root_causes(
    failed_tests: List[Dict[str, Any]],
    pattern_analysis: Dict[str, Any],
    test_summary: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """基于规则的接口测试根因分析（复用并扩展单元测试逻辑）"""
    root_causes = []

    if not failed_tests:
        return root_causes

    # 基于API类别的根因分析
    api_breakdown = pattern_analysis.get("api_category_breakdown", {})

    # API版本检查失败
    if "api_version" in api_breakdown and len(api_breakdown["api_version"]) >= 1:
        root_causes.append({
            "cause": f"KVM API版本不匹配：{len(api_breakdown['api_version'])}个版本检查失败，可能是内核版本或KVM配置问题",
            "likelihood": 0.9,
            "category": "api_version_mismatch"
        })

    # 扩展能力检查失败
    if "capability_check" in api_breakdown and len(api_breakdown["capability_check"]) >= 1:
        root_causes.append({
            "cause": f"KVM扩展能力不支持：{len(api_breakdown['capability_check'])}个能力检查失败，可能是硬件或内核配置不支持某些特性",
            "likelihood": 0.85,
            "category": "capability_unsupported"
        })

    # 目标配置问题
    if "target_config" in api_breakdown and len(api_breakdown["target_config"]) >= 1:
        root_causes.append({
            "cause": f"首选目标配置异常：{len(api_breakdown['target_config'])}个配置测试失败，可能是ARM架构配置或虚拟化设置问题",
            "likelihood": 0.8,
            "category": "target_config_issue"
        })

    # 基础接口问题
    if "basic_interface" in api_breakdown and len(api_breakdown["basic_interface"]) >= 1:
        root_causes.append({
            "cause": f"基础接口功能异常：{len(api_breakdown['basic_interface'])}个基础测试失败，可能是KVM核心功能问题",
            "likelihood": 0.9,
            "category": "basic_interface_failure"
        })

    # 基于严重程度的分析
    severity_breakdown = pattern_analysis.get("severity_breakdown", {})

    if "critical" in severity_breakdown and len(severity_breakdown["critical"]) >= 1:
        root_causes.append({
            "cause": f"系统级严重错误：{len(severity_breakdown['critical'])}个严重失败，可能导致系统不稳定",
            "likelihood": 0.95,
            "category": "critical_system_error"
        })

    if "assertion_failure" in severity_breakdown and len(severity_breakdown["assertion_failure"]) >= 2:
        root_causes.append({
            "cause": f"断言失败模式：{len(severity_breakdown['assertion_failure'])}个断言失败，可能是测试期望值与实际实现不匹配",
            "likelihood": 0.7,
            "category": "assertion_mismatch"
        })

    # 基于失败率的整体分析
    failure_rate = (test_summary.get("failed", 0) /
                    max(test_summary.get("total", 1), 1)) * 100

    if failure_rate > 10:
        root_causes.append({
            "cause": f"高失败率警告：失败率{failure_rate:.1f}%，可能存在系统性问题或环境配置错误",
            "likelihood": 0.8,
            "category": "systemic_issue"
        })

    # 如果没有明显的模式，提供通用根因
    if not root_causes:
        root_causes.append({
            "cause": "零散接口测试失败：失败的测试用例没有明显的共同模式，可能是独立的接口实现缺陷",
            "likelihood": 0.6,
            "category": "isolated_failures"
        })

    return root_causes


def generate_interface_test_suggestions(
    failed_tests: List[Dict[str, Any]],
    root_causes: List[Dict[str, Any]]
) -> List[str]:
    """基于失败测试和根因分析生成具体的检查建议（复用并扩展单元测试逻辑）"""
    suggestions = []

    if not failed_tests:
        return ["所有接口测试通过，无需额外检查"]

    # 基于根因类别生成建议
    cause_categories = {rc.get("category", "") for rc in root_causes}

    if "api_version_mismatch" in cause_categories:
        suggestions.extend([
            "检查KVM API版本：cat /sys/module/kvm/version",
            "验证内核版本兼容性：uname -r",
            "检查KVM模块加载状态：lsmod | grep kvm",
            "查看KVM相关内核日志：dmesg | grep -i kvm"
        ])

    if "capability_unsupported" in cause_categories:
        suggestions.extend([
            "检查CPU虚拟化支持：grep -E '(vmx|svm)' /proc/cpuinfo",
            "验证KVM扩展特性：ls /sys/module/kvm*/parameters/",
            "检查硬件虚拟化功能：cat /proc/cpuinfo | grep Features",
            "确认BIOS/UEFI虚拟化设置已启用"
        ])

    if "target_config_issue" in cause_categories:
        suggestions.extend([
            "检查ARM架构配置：cat /proc/cpuinfo | grep 'CPU architecture'",
            "验证首选目标设置：cat /proc/sys/kernel/kvm_*",
            "检查虚拟化配置参数：find /sys -name '*kvm*' -type f",
            "确认处理器架构兼容性"
        ])

    if "basic_interface_failure" in cause_categories:
        suggestions.extend([
            "检查KVM设备文件：ls -la /dev/kvm",
            "验证KVM服务状态：systemctl status kvm",
            "检查权限设置：groups | grep kvm",
            "测试基础KVM功能：kvm-ok 或 virt-host-validate"
        ])

    if "critical_system_error" in cause_categories:
        suggestions.extend([
            "立即检查系统日志：journalctl -u kvm -n 50",
            "查看内核错误信息：dmesg | tail -50",
            "检查系统资源使用：free -h && df -h",
            "验证系统稳定性：uptime && cat /proc/loadavg"
        ])

    # 基于具体失败原因的建议
    for failed_test in failed_tests:
        fail_reason = failed_test.get("raw", {}).get("fail_reason", "")
        if "version" in fail_reason.lower() and "should" in fail_reason.lower():
            suggestions.append("检查测试用例的期望值是否与当前KVM版本匹配")
        elif "capability" in fail_reason.lower() and "should return" in fail_reason.lower():
            suggestions.append("验证KVM能力标志的实际返回值与期望值")

    # 通用建议
    suggestions.extend([
        f"重新运行失败的接口测试：{', '.join([t.get('case', '')[:50] + '...' if len(t.get('case', '')) > 50 else t.get('case', '') for t in failed_tests[:3]])}",
        "检查测试环境与开发环境的一致性",
        "查看详细的接口测试日志以获取更多错误详情"
    ])

    # 去重并限制数量
    unique_suggestions = list(dict.fromkeys(suggestions))
    return unique_suggestions[:10]  # 最多返回10个建议


def analyze_interface_test_anomalies(
    records: List[Dict[str, Any]],
    test_summary: Dict[str, Any],
    k2_client=None
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """分析接口测试异常，生成AI分析结果（复用单元测试的分析架构）"""
    anomalies = []

    # 提取失败的测试用例（包括FAIL和ERROR）
    failed_tests = [r for r in records if r.get(
        "status") in ["FAIL", "ERROR"] and r.get("case")]

    if not failed_tests:
        # 没有失败的测试用例，返回空异常列表
        return anomalies, {"ai_analysis_success": False}

    # 分析失败模式
    pattern_analysis = analyze_interface_failure_patterns(failed_tests)

    # 生成根因分析
    root_causes = []
    ai_analysis_success = False

    if k2_client and k2_client.enabled():
        try:
            # 尝试使用AI增强分析
            root_causes = generate_ai_enhanced_interface_root_causes(
                failed_tests, pattern_analysis, test_summary, k2_client)
            ai_analysis_success = True
        except Exception as e:
            print(f"接口测试AI分析失败，降级到规则分析: {e}")
            # AI分析失败，降级到基于规则的分析
            root_causes = generate_interface_test_root_causes(
                failed_tests, pattern_analysis, test_summary)
    else:
        # 使用基于规则的分析
        root_causes = generate_interface_test_root_causes(
            failed_tests, pattern_analysis, test_summary)

    # 生成检查建议
    suggestions = generate_interface_test_suggestions(
        failed_tests, root_causes)

    # 为每个失败的测试用例创建异常记录
    for failed_test in failed_tests:
        test_name = failed_test.get("case", "")
        fail_reason = failed_test.get("failure_reason", "") or failed_test.get(
            "raw", {}).get("fail_reason", "")

        # 确定严重程度（基于失败原因）
        severity = "medium"  # 默认中等
        confidence = 0.8

        if any(keyword in fail_reason.lower() for keyword in ["crash", "panic", "segfault"]):
            severity = "high"
            confidence = 0.9
        elif any(keyword in fail_reason.lower() for keyword in ["故意", "测试", "expect"]):
            severity = "low"
            confidence = 0.6

        # 为每个测试用例找到对应的AI根因分析
        test_specific_root_causes = []
        test_specific_suggestions = []

        if ai_analysis_success and root_causes:
            # 从AI分析结果中找到对应这个测试用例的根因
            for root_cause in root_causes:
                if isinstance(root_cause, dict):
                    # 检查是否是针对当前测试用例的分析
                    if 'test_case' in root_cause:
                        # 格式: {"test_case": "xxx", "analysis": {...}, "solution": "..."}
                        if root_cause.get('test_case') == test_name or test_name.endswith(root_cause.get('test_case', '')):
                            if 'analysis' in root_cause and isinstance(root_cause['analysis'], dict):
                                analysis = root_cause['analysis']
                                test_specific_root_causes.append({
                                    "cause": analysis.get("cause", ""),
                                    "likelihood": analysis.get("likelihood", 0.5),
                                    "category": analysis.get("category", "general")
                                })
                            # 提取solution作为建议
                            if 'solution' in root_cause:
                                test_specific_suggestions.append(
                                    root_cause['solution'])
                    elif 'cause' in root_cause:
                        # 格式: {"cause": "xxx", "likelihood": 0.95, "category": "xxx"}
                        test_specific_root_causes.append({
                            "cause": root_cause.get("cause", ""),
                            "likelihood": root_cause.get("likelihood", 0.5),
                            "category": root_cause.get("category", "general")
                        })
                    elif 'test' in root_cause:
                        # 格式: {"test": "xxx", "cause": "xxx", ...}
                        if root_cause.get('test') == test_name or test_name.endswith(root_cause.get('test', '')):
                            test_specific_root_causes.append({
                                "cause": root_cause.get("cause", ""),
                                "likelihood": root_cause.get("likelihood", 0.5),
                                "category": root_cause.get("category", "general")
                            })

            # 如果没找到特定的根因，使用通用的
            if not test_specific_root_causes and root_causes:
                test_specific_root_causes = root_causes[:3]  # 最多取前3个通用根因

        anomaly = {
            "suite": "InterfaceTest",
            "case": test_name,
            "metric": "test_result",
            "current_value": failed_test.get("value", 0),
            "severity": severity,
            "confidence": confidence,
            "primary_reason": fail_reason or "接口测试失败",
            "supporting_evidence": {
                "test_name": test_name,
                "fail_reason": fail_reason,
                "logfile": failed_test.get("raw", {}).get("logfile", ""),
                "time_elapsed": failed_test.get("raw", {}).get("time_elapsed", 0),
                "test_category": failed_test.get("raw", {}).get("category", ""),
                "ai_enhanced": ai_analysis_success
            },
            "root_causes": test_specific_root_causes if test_specific_root_causes else root_causes,
            "suggestions": test_specific_suggestions if test_specific_suggestions else suggestions
        }
        anomalies.append(anomaly)

    return anomalies, {
        "ai_analysis_success": ai_analysis_success,
        "total_failed": len(failed_tests),
        "failure_patterns": pattern_analysis.get("failure_patterns", [])
    }


def generate_ai_enhanced_interface_root_causes(
    failed_tests: List[Dict[str, Any]],
    pattern_analysis: Dict[str, Any],
    test_summary: Dict[str, Any],
    k2_client
) -> List[Dict[str, Any]]:
    """
    使用AI增强的接口测试根因分析（复用单元测试的AI调用架构）

    接口测试的AI分析包含更丰富的上下文信息：测试名称、失败原因、日志路径等
    """
    try:
        # 准备AI分析的输入数据（接口测试特有的丰富信息）
        test_details = []
        for test in failed_tests:
            fail_reason = test.get("raw", {}).get("fail_reason", "")
            test_name = test.get("case", "")
            logfile = test.get("raw", {}).get("logfile", "")
            time_elapsed = test.get("raw", {}).get("time_elapsed", 0)

            # 构建详细的测试信息（比单元测试更丰富）
            detail = f"""测试用例: {test_name}
失败原因: {fail_reason}
执行时间: {time_elapsed:.3f}秒
日志文件: {logfile}"""
            test_details.append(detail)

        failure_rate = (test_summary.get("failed", 0) + test_summary.get(
            "errors", 0)) / max(test_summary.get("total", 1), 1) * 100

        # 构建接口测试专用的AI分析提示（强调使用详细失败原因）
        prompt = f"""
分析以下X Core KVM接口测试失败情况：

失败的测试用例详情（包含具体失败原因）：
{chr(10).join(test_details)}

失败统计：
- 总测试数：{test_summary.get("total", 0)}
- 失败数：{test_summary.get("failed", 0)}
- 错误数：{test_summary.get("errors", 0)}
- 失败率：{failure_rate:.1f}%

模式分析：
{pattern_analysis.get("failure_patterns", [])}

请重点基于每个测试的具体失败原因（fail_reason字段）进行深度分析，而不仅仅是测试名称。
分析要点：
1. 解读具体的错误信息和断言失败
2. 分析数值不匹配的原因（如期望值vs实际值）
3. 识别KVM API版本兼容性问题
4. 判断硬件虚拟化特性支持情况
5. 评估ARM架构配置问题
6. 检查内核模块和权限配置

每个根因分析应该直接引用具体的失败原因，并提供针对性的解决方案。
返回JSON格式，包含cause（原因）、likelihood（可能性0-1）、category（类别）字段。
"""

        # 调用AI模型进行真正的AI分析
        ai_response = _call_ai_for_interface_test_analysis(
            k2_client, prompt, [test.get("case", "") for test in failed_tests])

        print(f"接口测试AI分析响应: {ai_response}")

        if ai_response:
            # 处理不同的AI响应格式
            if "root_causes" in ai_response:
                print(f"使用接口测试AI分析结果: {ai_response['root_causes']}")
                return ai_response["root_causes"]
            elif isinstance(ai_response, list):
                # AI直接返回了根因数组，转换为标准格式
                root_causes = []
                for item in ai_response:
                    if isinstance(item, dict):
                        # 处理不同的AI响应格式
                        if 'cause' in item:
                            # 格式1: 直接包含cause字段
                            root_causes.append({
                                "cause": item.get("cause", ""),
                                "likelihood": item.get("likelihood", 0.5),
                                "category": item.get("category", "general")
                            })
                        elif 'analysis' in item and isinstance(item['analysis'], dict):
                            # 格式2: 嵌套在analysis字段中
                            analysis = item['analysis']
                            root_causes.append({
                                "cause": analysis.get("cause", ""),
                                "likelihood": analysis.get("likelihood", 0.5),
                                "category": analysis.get("category", "general")
                            })
                        elif 'test_case' in item:
                            # 格式3: 包含test_case的复杂格式，提取analysis部分
                            if 'analysis' in item and isinstance(item['analysis'], dict):
                                analysis = item['analysis']
                                root_causes.append({
                                    "cause": analysis.get("cause", ""),
                                    "likelihood": analysis.get("likelihood", 0.5),
                                    "category": analysis.get("category", "general")
                                })
                print(f"转换后的接口测试AI分析结果: {root_causes}")
                # 调试：检查每个root_cause的likelihood值
                for i, rc in enumerate(root_causes):
                    print(
                        f"Root cause {i}: likelihood={rc.get('likelihood')} (type: {type(rc.get('likelihood'))})")
                return root_causes
            else:
                print(f"接口测试AI响应格式不正确: {ai_response}")
                raise Exception("接口测试AI分析格式错误")
        else:
            print("接口测试AI响应为空")
            raise Exception("接口测试AI分析未返回有效结果")

    except Exception as e:
        # AI分析失败时回退到规则分析
        print(f"接口测试AI分析失败，回退到规则分析: {e}")

    # 回退到基于规则的分析
    return generate_interface_test_root_causes(failed_tests, pattern_analysis, test_summary)


def _call_ai_for_interface_test_analysis(k2_client, prompt: str, test_names: List[str]) -> Dict[str, Any]:
    """
    调用AI模型进行接口测试分析（复用单元测试的AI调用逻辑）

    真正调用AI大模型进行分析，基于测试用例名称、失败原因和上下文信息
    """
    try:
        # 复用单元测试的AI模型调用逻辑
        # 获取可用的模型
        available_models = [
            m for m in k2_client.models if m.enabled and m.error_count < 5]
        if not available_models:
            raise Exception("没有可用的AI模型")

        # 选择优先级最高的模型
        available_models.sort(key=lambda x: x.priority)
        model = available_models[0]

        print(f"正在调用AI模型 {model.name} 分析接口测试失败: {test_names}")

        # 构建AI请求
        url = model.api_base.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}

        # 添加API密钥（如果不是"EMPTY"）
        if model.api_key and model.api_key.upper() != "EMPTY":
            if "moonshot" in model.api_base:
                headers["Authorization"] = f"Bearer {model.api_key}"
            elif "anthropic" in model.api_base:
                headers["x-api-key"] = model.api_key
            else:
                headers["Authorization"] = f"Bearer {model.api_key}"

        # 接口测试专用的系统提示
        system_prompt = """你是一个专业的X Core KVM接口测试分析专家。请分析接口测试失败的根本原因，重点关注：
1. KVM API版本和兼容性问题
2. 硬件虚拟化特性支持情况
3. ARM架构相关的配置问题
4. 内核模块和权限配置问题
5. 接口实现与测试期望的匹配度

请提供准确的根因分析和可行的修复建议。"""

        data = {
            "model": model.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 2000
        }

        import requests
        resp = requests.post(url, headers=headers, json=data,
                             timeout=model.timeout or 120)
        resp.raise_for_status()

        response_data = resp.json()
        content = response_data["choices"][0]["message"]["content"]

        print(f"AI模型 {model.name} 响应内容: {content}")

        # 解析AI响应
        try:
            import json
            import re

            # 清理markdown格式的JSON
            content = content.strip()
            if content.startswith('```json'):
                content = content[7:]  # 移除```json
            if content.endswith('```'):
                content = content[:-3]  # 移除```
            content = content.strip()

            # 尝试提取JSON部分
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                ai_result = json.loads(json_str)
                # 如果AI直接返回了数组，包装为正确格式
                if isinstance(ai_result, list):
                    ai_result = {"root_causes": ai_result}
            else:
                # 尝试提取对象格式
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group()
                    ai_result = json.loads(json_str)
                else:
                    # 如果没有找到JSON，尝试解析整个响应
                    ai_result = json.loads(content)

            # 确保返回格式正确
            if "root_causes" not in ai_result:
                # 如果AI直接返回了root_causes数组
                if isinstance(ai_result, list):
                    ai_result = {"root_causes": ai_result}
                else:
                    # 尝试从其他字段提取
                    ai_result = {"root_causes": [ai_result]}

            return ai_result

        except json.JSONDecodeError as e:
            print(f"AI响应JSON解析失败: {e}")
            raise Exception(f"AI响应格式错误: {content}")

    except Exception as e:
        print(f"调用AI模型失败: {e}")
        # 重新抛出异常，让上层处理降级
        raise
