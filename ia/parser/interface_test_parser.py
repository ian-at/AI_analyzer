from __future__ import annotations

import json
import re
from typing import Any


def _norm_name(s: str) -> str:
    """标准化测试名称"""
    return re.sub(r"\s+", " ", s.strip())


def _format_interface_test_name(test_name: str) -> str:
    """格式化接口测试用例名称，提取方法名

    输入: interface_tests/test_xcore_basic_interfaces.py:TestXcoreGetApiVersion.test_api_version_basic
    输出: test_api_version_basic
    """
    if not test_name:
        return test_name

    # 提取方法名部分
    # 格式: path/file.py:ClassName.method_name
    if ":" in test_name:
        # 获取冒号后的部分：ClassName.method_name
        class_method = test_name.split(":")[-1]

        if "." in class_method:
            # 只取方法名部分
            method_name = class_method.split(".", 1)[1]
            return method_name
        else:
            # 如果没有方法名，返回类名
            return class_method

    # 如果格式不符合预期，返回原始名称
    return test_name


def parse_interface_test_log(log_text: str) -> list[dict[str, Any]]:
    """解析接口测试日志文件，提取每个测试用例的结果。

    接口测试日志为JSON格式，包含详细的测试用例信息和失败原因。

    产出统一记录：
    - suite: "InterfaceTest"
    - case: 测试用例名称
    - metric: "test_result"
    - value: 1 (PASS) 或 0 (FAIL/ERROR)
    - unit: "result"
    - status: "PASS", "FAIL", "ERROR", "SKIP"
    - raw: 原始测试数据，包含失败原因、日志文件路径等详细信息
    """
    try:
        # 解析JSON格式的日志
        data = json.loads(log_text)
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        return []

    records: list[dict[str, Any]] = []

    # 解析每个测试用例
    tests = data.get("tests", [])
    for test in tests:
        # 格式化测试用例名称为更简洁的格式
        raw_test_name = test.get("name", "")
        test_name = _format_interface_test_name(raw_test_name)
        status = test.get("status", "UNKNOWN").upper()

        # 转换状态为数值：PASS=1, FAIL/ERROR=0, SKIP保持为0但状态不同
        if status == "PASS":
            value = 1
        elif status in ["FAIL", "ERROR"]:
            value = 0
        elif status == "SKIP":
            value = 0  # 跳过的测试不计入失败，但value为0
        else:
            value = 0  # 未知状态默认为失败

        # 提取失败原因和详细信息（这是接口测试的重要特色）
        fail_reason = test.get("fail_reason", "")
        logfile = test.get("logfile", "")
        logdir = test.get("logdir", "")
        time_elapsed = test.get("time_elapsed", 0.0)

        # 构建记录
        record = {
            "suite": "InterfaceTest",
            "case": test_name,
            "metric": "test_result",
            "value": value,
            "unit": "result",
            "status": status,
            "raw": {
                "test_id": test.get("id", ""),
                "test_name": test_name,           # 格式化后的名称
                "raw_test_name": raw_test_name,   # 保留原始完整名称
                "fail_reason": fail_reason,      # 重要：失败原因信息
                "logfile": logfile,              # 重要：详细日志文件路径
                "logdir": logdir,
                "time_elapsed": time_elapsed,
                "actual_time_start": test.get("actual_time_start", 0),
                "actual_time_end": test.get("actual_time_end", 0),
                "tags": test.get("tags", {}),
                "whiteboard": test.get("whiteboard", "")
            }
        }
        records.append(record)

    # 添加总结信息记录（与单元测试保持一致的格式）
    total_tests = len(tests)
    passed_tests = data.get("pass", 0)
    failed_tests = data.get("failures", 0)
    error_tests = data.get("errors", 0)
    skipped_tests = data.get("skip", 0)
    cancelled_tests = data.get("cancel", 0)
    interrupted_tests = data.get("interrupt", 0)

    # 总结记录
    summary_records = [
        {
            "suite": "InterfaceTest",
            "case": None,  # 总结信息没有具体的case
            "metric": "total_tests",
            "value": total_tests,
            "unit": "count",
            "status": "INFO",
            "raw": {"description": "总测试用例数"}
        },
        {
            "suite": "InterfaceTest",
            "case": None,
            "metric": "passed_tests",
            "value": passed_tests,
            "unit": "count",
            "status": "INFO",
            "raw": {"description": "通过的测试用例数"}
        },
        {
            "suite": "InterfaceTest",
            "case": None,
            "metric": "failed_tests",
            "value": failed_tests,
            "unit": "count",
            "status": "INFO",
            "raw": {"description": "失败的测试用例数"}
        },
        {
            "suite": "InterfaceTest",
            "case": None,
            "metric": "error_tests",
            "value": error_tests,
            "unit": "count",
            "status": "INFO",
            "raw": {"description": "错误的测试用例数"}
        },
        {
            "suite": "InterfaceTest",
            "case": None,
            "metric": "skipped_tests",
            "value": skipped_tests,
            "unit": "count",
            "status": "INFO",
            "raw": {"description": "跳过的测试用例数"}
        },
        {
            "suite": "InterfaceTest",
            "case": None,
            "metric": "final_result",
            "value": 1 if (failed_tests + error_tests) == 0 else 0,
            "unit": "result",
            "status": "PASS" if (failed_tests + error_tests) == 0 else "FAIL",
            "raw": {
                "description": "整体测试结果",
                "job_id": data.get("job_id", ""),
                "start_time": data.get("start", ""),
                "debuglog": data.get("debuglog", "")
            }
        }
    ]

    # 将总结记录添加到记录列表
    records.extend(summary_records)

    return records


def get_failed_interface_test_cases(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从解析结果中提取失败的接口测试用例"""
    failed_cases = []
    for record in records:
        if (record.get("suite") == "InterfaceTest" and
            record.get("case") and  # 有具体的测试用例名称
                record.get("status") in ["FAIL", "ERROR"]):
            failed_cases.append(record)
    return failed_cases


def get_interface_test_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """从解析结果中提取接口测试总结信息"""
    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "success_rate": 0.0,
        "final_result": "UNKNOWN"
    }

    for record in records:
        if record.get("suite") == "InterfaceTest" and not record.get("case"):
            metric = record.get("metric", "")
            if metric == "total_tests":
                summary["total"] = record.get("value", 0)
            elif metric == "passed_tests":
                summary["passed"] = record.get("value", 0)
            elif metric == "failed_tests":
                summary["failed"] = record.get("value", 0)
            elif metric == "error_tests":
                summary["errors"] = record.get("value", 0)
            elif metric == "skipped_tests":
                summary["skipped"] = record.get("value", 0)
            elif metric == "final_result":
                summary["final_result"] = record.get("status", "UNKNOWN")

    # 计算成功率
    total_executable = summary["total"] - summary["skipped"]  # 排除跳过的测试
    if total_executable > 0:
        success_rate = (summary["passed"] / total_executable) * 100
        summary["success_rate"] = round(success_rate, 2)  # 精确到2位小数

    return summary


def extract_interface_test_failure_details(failed_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """提取接口测试失败用例的详细信息，用于AI分析

    这是接口测试特有的功能，提取失败原因和相关上下文信息
    """
    failure_details = []

    for case in failed_cases:
        raw_data = case.get("raw", {})

        detail = {
            "test_name": case.get("case", ""),
            "test_id": raw_data.get("test_id", ""),
            "status": case.get("status", ""),
            "fail_reason": raw_data.get("fail_reason", ""),  # 关键：失败原因
            "logfile": raw_data.get("logfile", ""),          # 关键：详细日志路径
            "logdir": raw_data.get("logdir", ""),
            "time_elapsed": raw_data.get("time_elapsed", 0.0),
            # 测试分类
            "category": _categorize_interface_test(case.get("case", "")),
            # 严重程度
            "severity": _assess_failure_severity(raw_data.get("fail_reason", ""))
        }

        failure_details.append(detail)

    return failure_details


def _categorize_interface_test(test_name: str) -> str:
    """根据测试名称对接口测试进行分类"""
    test_name_lower = test_name.lower()

    if "api_version" in test_name_lower:
        return "API版本检查"
    elif "extension" in test_name_lower or "capability" in test_name_lower:
        return "扩展能力检查"
    elif "preferred_target" in test_name_lower:
        return "首选目标配置"
    elif "basic" in test_name_lower:
        return "基础功能测试"
    elif "invalid" in test_name_lower or "error" in test_name_lower:
        return "错误处理测试"
    elif "consistency" in test_name_lower:
        return "一致性验证"
    elif "boundary" in test_name_lower or "limit" in test_name_lower:
        return "边界条件测试"
    elif "performance" in test_name_lower or "timing" in test_name_lower:
        return "性能测试"
    else:
        return "其他接口测试"


def _assess_failure_severity(fail_reason: str) -> str:
    """根据失败原因评估严重程度"""
    if not fail_reason or fail_reason == "<unknown>":
        return "medium"

    fail_reason_lower = fail_reason.lower()

    # 高严重程度：系统级错误、安全问题
    if any(keyword in fail_reason_lower for keyword in [
        "crash", "panic", "segfault", "memory", "security", "privilege", "corruption"
    ]):
        return "high"

    # 中等严重程度：功能性错误、API不匹配
    elif any(keyword in fail_reason_lower for keyword in [
        "version", "capability", "api", "interface", "not equal", "mismatch"
    ]):
        return "medium"

    # 低严重程度：配置问题、预期值错误
    elif any(keyword in fail_reason_lower for keyword in [
        "config", "expect", "should", "故意", "测试"
    ]):
        return "low"

    else:
        return "medium"  # 默认中等严重程度
