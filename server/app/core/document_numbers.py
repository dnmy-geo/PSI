"""按「前缀 + 日期 + 四位流水」生成单据号。

销售订单/出库/退货、采购订单都用这一套：流水存各自的计数表，取号前调用方把组织行
``FOR UPDATE`` 锁住即可串行化（见各 create_* 服务）。表名与计数表名都是代码内的常量，
不接受调用方传入的任意字符串。
"""

import re
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def next_document_number(db: Session, org: UUID, document_date: date, *,
                         prefix: str, table: str, counter: str) -> str:
    head = f"{prefix}{document_date:%Y%m%d}"
    existing = db.execute(text(f"""
        SELECT document_no FROM {table}
        WHERE organization_id = :org AND document_no LIKE :pattern
    """), {"org": org, "pattern": f"{head}%"}).scalars()
    # 计数表可能落后于手填过的单号，取两者较大值再 +1。
    last_existing = max((int(match.group(1)) for number in existing
                         if (match := re.fullmatch(rf"{head}(\d+)", number))), default=0)
    sequence = db.execute(text(f"""
        INSERT INTO {counter} (organization_id, document_date, last_value)
        VALUES (:org, :date, :next_value)
        ON CONFLICT (organization_id, document_date) DO UPDATE
          SET last_value = GREATEST({counter}.last_value + 1, EXCLUDED.last_value)
        RETURNING last_value
    """), {"org": org, "date": document_date,
           "next_value": last_existing + 1}).scalar_one()
    return f"{head}{sequence:04d}"
