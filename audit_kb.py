"""只读审计 RAGNEXUS Chroma 知识库。

用途：
1. 识别完全重复和极高相似度知识块；
2. 标记可能包含个人信息的知识块；
3. 输出 JSON 与 Markdown 报告，不执行删除。

运行：python audit_kb.py
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from security_config import load_api_key

ROOT = Path(__file__).resolve().parent
API_URL = os.environ.get("RAG_API_URL", "http://localhost:8000/kb/docs")
REPORT_JSON = ROOT / "kb_audit_report.json"
REPORT_MD = ROOT / "kb_audit_report.md"


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


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


def preview(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else compact[:limit] + "…"


def fetch_records(max_attempts: int = 12, retry_delay: int = 5) -> list[dict]:
    env = load_env(ROOT / ".env")
    api_key = load_api_key({**env, **os.environ})
    request = Request(API_URL, headers={"X-API-Key": api_key})
    payload = None

    for attempt in range(1, max_attempts + 1):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError(
                    f"API 鉴权失败（HTTP {exc.code}）。请确认 .env 中 RAG_API_KEY 与容器一致。"
                ) from exc
            error = f"HTTP {exc.code}"
        except (URLError, ConnectionError, OSError) as exc:
            error = str(exc)

        if attempt == max_attempts:
            raise RuntimeError(
                f"等待 RAG API 启动超时：{API_URL}\n最后错误：{error}\n"
                "请运行 docker compose ps 和 docker compose logs --tail=100 rag-api 检查容器。"
            )
        print(f"API 尚未就绪（{attempt}/{max_attempts}）：{error}；{retry_delay} 秒后重试…")
        time.sleep(retry_delay)

    if payload is None:
        raise RuntimeError("API 未返回有效数据")

    records = payload.get("records")
    if records:
        return records

    # 兼容尚未重启、只返回 documents 的旧接口。
    return [
        {"id": f"unknown_{index}", "document": text, "metadata": {}}
        for index, text in enumerate(payload.get("documents", []))
    ]


PII_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("指定学校", re.compile(r"岭南师范学院", re.I)),
    ("教育机构", re.compile(r"[\u4e00-\u9fff]{2,18}(?:大学|学院|学校|中学|小学)(?!会|习)")),
    ("简历/身份描述", re.compile(r"(?:个人简历|自我介绍|求职意向|教育经历|工作经历|实习经历|本人姓名|我的名字|学号|籍贯|出生年月|政治面貌)")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("邮箱", re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)),
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("联系方式", re.compile(r"(?:联系电话|联系方式|手机号|微信号|QQ号|家庭住址|现居地址|通信地址)")),
]


def find_exact_duplicates(records: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        key = normalize(record.get("document", ""))
        if key:
            groups[key].append(record)

    return [
        {
            "keep_id": group[0]["id"],
            "duplicate_ids": [item["id"] for item in group[1:]],
            "count": len(group),
            "preview": preview(group[0].get("document", "")),
            "sources": [item.get("metadata", {}).get("source") for item in group],
        }
        for group in groups.values()
        if len(group) > 1
    ]


def find_near_duplicates(records: list[dict], threshold: float = 0.97) -> list[dict]:
    """保守识别极高相似文本，避免把正常的相邻分块重叠误判为重复。"""
    buckets: dict[str, list[tuple[dict, str]]] = defaultdict(list)
    for record in records:
        norm = normalize(record.get("document", ""))
        if len(norm) < 40:
            continue
        # 仅比较长度接近且开头相近的文本，控制误报与复杂度。
        bucket = f"{round(len(norm) / 20)}:{norm[:10]}"
        buckets[bucket].append((record, norm))

    pairs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for items in buckets.values():
        for i in range(len(items)):
            left, left_norm = items[i]
            for j in range(i + 1, len(items)):
                right, right_norm = items[j]
                if left_norm == right_norm:
                    continue
                ratio = SequenceMatcher(None, left_norm, right_norm, autojunk=False).ratio()
                if ratio < threshold:
                    continue
                pair_key = tuple(sorted((left["id"], right["id"])))
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                pairs.append({
                    "left_id": left["id"],
                    "right_id": right["id"],
                    "similarity": round(ratio, 4),
                    "left_preview": preview(left.get("document", "")),
                    "right_preview": preview(right.get("document", "")),
                })
    return pairs


def find_personal_candidates(records: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    for record in records:
        text = record.get("document", "")
        matches: list[dict] = []
        for label, pattern in PII_RULES:
            found = sorted(set(pattern.findall(text)))
            if found:
                matches.append({"type": label, "matches": found[:10]})
        if matches:
            candidates.append({
                "id": record["id"],
                "source": record.get("metadata", {}).get("source"),
                "matches": matches,
                "preview": preview(text, 260),
            })
    return candidates


def write_markdown(report: dict) -> None:
    lines = [
        "# RAGNEXUS 知识库只读审计报告",
        "",
        f"- 知识块总数：**{report['total_records']}**",
        f"- 完全重复组：**{len(report['exact_duplicate_groups'])}**",
        f"- 完全重复冗余块：**{report['exact_duplicate_records']}**",
        f"- 极高相似候选对：**{len(report['near_duplicate_pairs'])}**",
        f"- 个人信息候选块：**{len(report['personal_candidates'])}**",
        "",
        "> 本报告不执行删除。unknown_ 开头的 ID 表示服务尚未重启，无法据此安全删除。",
        "",
        "## 完全重复",
        "",
    ]

    if not report["exact_duplicate_groups"]:
        lines.append("未发现完全重复内容。")
    for index, group in enumerate(report["exact_duplicate_groups"], 1):
        lines.extend([
            f"### {index}. 保留 `{group['keep_id']}`，候选删除 {', '.join(f'`{item}`' for item in group['duplicate_ids'])}",
            "",
            f"- 出现次数：{group['count']}",
            f"- 来源：{group['sources']}",
            f"- 摘要：{group['preview']}",
            "",
        ])

    lines.extend(["## 极高相似候选", ""])
    if not report["near_duplicate_pairs"]:
        lines.append("未发现相似度 ≥ 0.97 的非完全重复内容。")
    for index, pair in enumerate(report["near_duplicate_pairs"], 1):
        lines.extend([
            f"### {index}. `{pair['left_id']}` ↔ `{pair['right_id']}`（{pair['similarity']:.2%}）",
            "",
            f"- A：{pair['left_preview']}",
            f"- B：{pair['right_preview']}",
            "",
        ])

    lines.extend(["## 个人信息候选", ""])
    if not report["personal_candidates"]:
        lines.append("未发现符合当前规则的个人信息候选。")
    for index, item in enumerate(report["personal_candidates"], 1):
        labels = "；".join(
            f"{match['type']}：{', '.join(match['matches'])}"
            for match in item["matches"]
        )
        lines.extend([
            f"### {index}. `{item['id']}`",
            "",
            f"- 来源：{item['source']}",
            f"- 命中：{labels}",
            f"- 摘要：{item['preview']}",
            "",
        ])

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    records = fetch_records()
    exact = find_exact_duplicates(records)
    report = {
        "total_records": len(records),
        "exact_duplicate_groups": exact,
        "exact_duplicate_records": sum(len(group["duplicate_ids"]) for group in exact),
        "near_duplicate_pairs": find_near_duplicates(records),
        "personal_candidates": find_personal_candidates(records),
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report)
    print(f"审计完成：{REPORT_MD}")
    print(
        f"总数={report['total_records']}，完全重复冗余={report['exact_duplicate_records']}，"
        f"高相似候选={len(report['near_duplicate_pairs'])}，"
        f"个人信息候选={len(report['personal_candidates'])}"
    )


if __name__ == "__main__":
    main()
