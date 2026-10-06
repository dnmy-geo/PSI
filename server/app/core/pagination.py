"""精确分页总数。

列表接口用 LIMIT/OFFSET 取页，本身无法告诉调用方一共有多少行；只靠"多取一条"探测
得到的是估算值，页码会随翻页不断变大。这里把总数放进 `X-Total-Count` 响应头——正文
保持原来的裸数组，不破坏既有调用方。

计数复用与列表完全相同的 SQL 与参数（包成子查询），因此过滤条件只有一份，不会出现
"列表过滤了、计数没过滤"这类漂移。
"""

import re
from typing import Any

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

# 计数时要去掉分页尾巴，否则子查询会把"取几行"也算进去。容忍写死在 SQL 里的 LIMIT/OFFSET。
_LIMIT_TAIL = re.compile(r"\s+LIMIT\s+:limit\s+OFFSET\s+:offset\s*$", re.IGNORECASE)


def count_rows(db: Session, query: str, params: dict[str, Any]) -> int:
    """统计 query 会返回的行数。query 若带 `LIMIT :limit OFFSET :offset` 会自动去掉。"""
    return db.execute(text(f"SELECT count(*) FROM ({_LIMIT_TAIL.sub('', query.strip())}) AS counted_rows"),
                      params).scalar_one()


def paginate(db: Session, query: str, params: dict[str, Any], *,
             limit: int, offset: int, response: Response | None = None) -> list[dict]:
    """取一页数据，并把精确总数写进 X-Total-Count。

    计数与取页复用同一段 SQL 和同一份参数，过滤条件只有一份，不会出现
    "列表过滤了、计数没过滤"这类漂移。

    调用方没有 HTTP 响应可写时（例如工作台内部取前 N 条）可省略 response，
    此时只取页、不写响应头。
    """
    total = count_rows(db, query, params)
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
    rows = db.execute(text(f"{_LIMIT_TAIL.sub('', query.strip())} LIMIT :limit OFFSET :offset"),
                      {**params, "limit": limit, "offset": offset}).mappings()
    return [dict(row) for row in rows]
