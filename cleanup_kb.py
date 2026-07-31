"""执行已确认的 RAGNEXUS 知识库清理。

清理范围：
1. 删除 kb_audit_report.json 中每个完全重复组的 duplicate_ids；
2. 删除当前知识库中所有包含“岭南师范学院”的记录；
3. 删除前完整备份目标记录，删除后重新验证。

运行前须先重启 API，使 /kb/docs/delete 生效：
    docker compose restart rag-api
    python cleanup_kb.py
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
API_ROOT = os.environ.get("RAG_API_ROOT", "http://localhost:8000")
REPORT_PATH = ROOT / "kb_audit_report.json"
BACKUP_DIR = ROOT / "kb_backups"
SENSITIVE_TERM = "岭南师范学院"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


ENV = load_env(ROOT / ".env")
API_KEY = os.environ.get("RAG_API_KEY") or ENV.get("RAG_API_KEY") or "rag-secret-key-2024"


def api_json(path: str, method: str = "GET", payload: dict | None = None, attempts: int = 12) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"X-API-Key": API_KEY}
    if data is not None:
        headers["Content-Type"] = "application/json"

    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            request = Request(API_ROOT + path, data=data, headers=headers, method=method)
            with urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (401, 403, 404, 405, 422):
                raise RuntimeError(f"API 请求失败：HTTP {exc.code} {body}") from exc
            last_error = f"HTTP {exc.code} {body}"
        except (URLError, ConnectionError, OSError) as exc:
            last_error = str(exc)

        if attempt == attempts:
            break
        print(f"API 尚未就绪（{attempt}/{attempts}）：{last_error}；5 秒后重试…")
        time.sleep(5)

    raise RuntimeError(
        f"等待 API 超时：{API_ROOT + path}\n最后错误：{last_error}\n"
        "请运行 docker compose ps 和 docker compose logs --tail=100 rag-api。"
    )


def load_report() -> dict:
    if not REPORT_PATH.exists():
        raise RuntimeError("缺少 kb_audit_report.json，请先运行 python audit_kb.py")
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def main() -> None:
    report = load_report()
    payload = api_json("/kb/docs")
    records = payload.get("records", [])
    if not records:
        raise RuntimeError("/kb/docs 未返回 records。请先重启 rag-api，使最新版接口生效。")

    current_by_id = {record["id"]: record for record in records}
    duplicate_ids = {
        doc_id
        for group in report.get("exact_duplicate_groups", [])
        for doc_id in group.get("duplicate_ids", [])
    }
    if any(doc_id.startswith("unknown_") for doc_id in duplicate_ids):
        raise RuntimeError("审计报告没有真实 Chroma ID，请重启 API 后重新运行 audit_kb.py")

    missing_duplicates = sorted(duplicate_ids - set(current_by_id))
    if missing_duplicates:
        raise RuntimeError(
            "知识库在审计后发生变化，部分重复 ID 已不存在。为避免误操作已中止。\n"
            f"缺失数量：{len(missing_duplicates)}，示例：{missing_duplicates[:10]}\n"
            "请重新运行 python audit_kb.py 后再执行本脚本。"
        )

    sensitive_ids = {
        record["id"]
        for record in records
        if SENSITIVE_TERM in record.get("document", "")
        or SENSITIVE_TERM in str(record.get("metadata", {}).get("source", ""))
    }
    delete_ids = sorted(duplicate_ids | sensitive_ids)
    delete_records = [current_by_id[doc_id] for doc_id in delete_ids]

    expected_duplicate_count = report.get("exact_duplicate_records")
    if len(duplicate_ids) != expected_duplicate_count:
        raise RuntimeError(
            f"报告统计不一致：统计值={expected_duplicate_count}，实际重复 ID={len(duplicate_ids)}。已中止。"
        )
    if not sensitive_ids:
        raise RuntimeError(f"当前知识库未找到“{SENSITIVE_TERM}”，与已确认范围不一致。已中止。")

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"kb_cleanup_backup_{stamp}.json"
    backup = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "before_count": len(records),
        "duplicate_ids": sorted(duplicate_ids),
        "sensitive_ids": sorted(sensitive_ids),
        "delete_ids": delete_ids,
        "records": delete_records,
    }
    backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已备份 {len(delete_records)} 个待删除块：{backup_path}")

    result = api_json("/kb/docs/delete", method="POST", payload={"ids": delete_ids}, attempts=3)
    if result.get("deleted") != len(delete_ids):
        raise RuntimeError(
            f"删除数量异常：计划={len(delete_ids)}，API 返回={result.get('deleted')}，"
            f"missing={result.get('missing')}。备份位于 {backup_path}"
        )

    after = api_json("/kb/docs")
    remaining_records = after.get("records", [])
    remaining_ids = {record["id"] for record in remaining_records}
    undeleted = sorted(set(delete_ids) & remaining_ids)
    sensitive_remaining = [
        record["id"]
        for record in remaining_records
        if SENSITIVE_TERM in record.get("document", "")
        or SENSITIVE_TERM in str(record.get("metadata", {}).get("source", ""))
    ]
    if undeleted or sensitive_remaining:
        raise RuntimeError(
            f"删除后验证失败：未删除 ID={undeleted[:10]}，敏感词残留={sensitive_remaining[:10]}。"
        )

    summary = {
        "before": len(records),
        "deleted": len(delete_ids),
        "duplicates_deleted": len(duplicate_ids),
        "sensitive_records_deleted": len(sensitive_ids),
        "overlap": len(duplicate_ids & sensitive_ids),
        "remaining": len(remaining_records),
        "backup": str(backup_path),
        "api_result": result,
    }
    summary_path = ROOT / "kb_cleanup_result.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("清理与基础验证完成")
    print(f"清理前={summary['before']}")
    print(f"删除重复块={summary['duplicates_deleted']}")
    print(f"删除学校相关块={summary['sensitive_records_deleted']}（其中与重复项重叠 {summary['overlap']}）")
    print(f"实际删除总数={summary['deleted']}")
    print(f"剩余={summary['remaining']}")
    print(f"结果记录={summary_path}")
    print("请再次运行 python audit_kb.py 进行最终重复检查。")


if __name__ == "__main__":
    main()
