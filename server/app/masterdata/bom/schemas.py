from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class BomLineWrite(BaseModel):
    child_item_id: UUID
    quantity_base: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    sort_order: int = 0


class BomWrite(BaseModel):
    parent_item_id: UUID
    version: int = Field(gt=0)
    lines: list[BomLineWrite] = Field(min_length=1)


class BomLineRead(BomLineWrite):
    id: UUID


class BomRead(BaseModel):
    id: UUID
    organization_id: UUID
    parent_item_id: UUID
    version: int
    is_active: bool
    lines: list[BomLineRead]


class BomTreeNode(BaseModel):
    """多级用料清单展开后的一个用料行。子行沿用同一结构，形成树。"""
    id: UUID                      # bom_lines.id（真实数据）
    # 行键必须按路径唯一：同一个半成品的用料会在多个父节点下重复出现，
    # 直接用行 id 当 React key 会冲突，导致收起时子树收不干净。
    path_key: str
    item_id: UUID                 # 该行指向的物料（有启用 BOM 时会继续展开）
    quantity_base: Decimal        # 按该物料的基本单位计
    unit_code: str | None = None  # 基本单位编码（KG / PCS / BAG…），逐行不同故随行下发
    children: list["BomTreeNode"] = []


class BomSummary(BaseModel):
    """列表行：一行一个 BOM 头，`children` 是它多级展开后的用料树。"""
    id: UUID
    organization_id: UUID
    parent_item_id: UUID
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # 树的根节点也带 item_id / row_kind，这样前后端可以按同一套字段渲染整棵树。
    item_id: UUID
    row_kind: str = "bom"
    path_key: str = ""
    quantity_base: Decimal | None = None
    unit_code: str | None = None
    children: list[BomTreeNode] = []

