from __future__ import annotations

import re
from typing import Any


def _norm_name(s: str) -> str:
    """标准化测试名称"""
    return re.sub(r"\s+", " ", s.strip())


def parse_unit_test_log(log_text: str) -> list[dict[str, Any]]:
    """解析单元测试日志文件，提取每个测试用例的结果。

    产出统一记录：
    - suite: "UnitTest"
    - case: 测试用例名称
    - metric: "test_result"
    - value: 1 (PASS) 或 0 (FAIL)
    - unit: "result"
    - status: "PASS" 或 "FAIL"
    - raw: 原始行内容和解析细节
    """
    lines = [ln.rstrip() for ln in log_text.splitlines()]
    records: list[dict[str, Any]] = []

    # 测试用例行的正则表达式
    # 匹配格式: test[N] test_name ... PASS/FAIL
    test_case_pat = re.compile(
        r"test\[(?P<test_num>\d+)\]\s+(?P<test_name>\S+)\s+\.\.\.\s+(?P<status>PASS|FAIL)",
        re.IGNORECASE
    )

    # 总结信息的正则表达式
    total_pat = re.compile(r"Total:\s*(?P<total>\d+)", re.IGNORECASE)
    passed_pat = re.compile(r"Passed:\s*(?P<passed>\d+)", re.IGNORECASE)
    failed_pat = re.compile(r"Failed:\s*(?P<failed>\d+)", re.IGNORECASE)
    ignored_pat = re.compile(r"Ignored:\s*(?P<ignored>\d+)", re.IGNORECASE)

    # 最终结果的正则表达式
    final_result_pat = re.compile(
        r"(?:All\s+.*\s+unit\s+tests|.*\s+unit\s+tests)\s+(PASSED|FAILED)!", re.IGNORECASE
    )

    summary_info = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "ignored": 0,
        "final_result": "UNKNOWN"
    }

    for ln in lines:
        s = ln.strip()
        if not s:
            continue

        # 解析测试用例结果
        test_match = test_case_pat.search(s)
        if test_match:
            test_num = int(test_match.group("test_num"))
            test_name = _norm_name(test_match.group("test_name"))
            status = test_match.group("status").upper()

            # 转换状态为数值：PASS=1, FAIL=0
            value = 1 if status == "PASS" else 0

            records.append({
                "suite": "UnitTest",
                "case": test_name,
                "metric": "test_result",
                "value": value,
                "unit": "result",
                "status": status,
                "raw": {
                    "line": s,
                    "test_number": test_num,
                    "test_name": test_name
                }
            })
            continue

        # 解析总结信息
        total_match = total_pat.search(s)
        if total_match:
            summary_info["total"] = int(total_match.group("total"))
            continue

        passed_match = passed_pat.search(s)
        if passed_match:
            summary_info["passed"] = int(passed_match.group("passed"))
            continue

        failed_match = failed_pat.search(s)
        if failed_match:
            summary_info["failed"] = int(failed_match.group("failed"))
            continue

        ignored_match = ignored_pat.search(s)
        if ignored_match:
            summary_info["ignored"] = int(ignored_match.group("ignored"))
            continue

        # 解析最终结果
        final_match = final_result_pat.search(s)
        if final_match:
            summary_info["final_result"] = final_match.group(1).upper()
            continue

    # 添加总结记录
    records.extend([
        {
            "suite": "UnitTest",
            "case": "",
            "metric": "total_tests",
            "value": summary_info["total"],
            "unit": "count",
            "status": "",
            "raw": {"summary": summary_info}
        },
        {
            "suite": "UnitTest",
            "case": "",
            "metric": "passed_tests",
            "value": summary_info["passed"],
            "unit": "count",
            "status": "PASS",
            "raw": {"summary": summary_info}
        },
        {
            "suite": "UnitTest",
            "case": "",
            "metric": "failed_tests",
            "value": summary_info["failed"],
            "unit": "count",
            "status": "FAIL" if summary_info["failed"] > 0 else "",
            "raw": {"summary": summary_info}
        },
        {
            "suite": "UnitTest",
            "case": "",
            "metric": "ignored_tests",
            "value": summary_info["ignored"],
            "unit": "count",
            "status": "",
            "raw": {"summary": summary_info}
        },
        {
            "suite": "UnitTest",
            "case": "",
            "metric": "success_rate",
            "value": (summary_info["passed"] / summary_info["total"] * 100) if summary_info["total"] > 0 else 0,
            "unit": "percentage",
            "status": summary_info["final_result"],
            "raw": {"summary": summary_info}
        }
    ])

    return records


def get_failed_test_cases(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从解析结果中提取失败的测试用例"""
    failed_cases = []
    for record in records:
        if (record.get("suite") == "UnitTest" and
            record.get("case") and  # 有具体的测试用例名称
                record.get("status") == "FAIL"):
            failed_cases.append(record)
    return failed_cases


def get_test_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """从解析结果中提取测试总结信息"""
    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "ignored": 0,
        "success_rate": 0.0,
        "final_result": "UNKNOWN"
    }

    for record in records:
        if record.get("suite") == "UnitTest" and not record.get("case"):
            metric = record.get("metric", "")
            if metric == "total_tests":
                summary["total"] = record.get("value", 0)
            elif metric == "passed_tests":
                summary["passed"] = record.get("value", 0)
            elif metric == "failed_tests":
                summary["failed"] = record.get("value", 0)
            elif metric == "ignored_tests":
                summary["ignored"] = record.get("value", 0)
            elif metric == "success_rate":
                summary["success_rate"] = record.get("value", 0.0)
                summary["final_result"] = record.get("status", "UNKNOWN")

    return summary
