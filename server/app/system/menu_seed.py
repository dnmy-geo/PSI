"""Default first- and second-level menu catalog for initial deployment."""

from sqlalchemy import text
from sqlalchemy.orm import Session


MENU_GROUPS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("workbench", "工作台", (("tasks", "我的待办"), ("alerts", "预警提醒"),
                           ("overview", "业务概览"))),
    ("business_flow", "业务全景", ()),
    ("sales", "销售", (("orders", "销售订单"), ("shipments", "销售出库"),
                         ("returns", "销售退货"))),
    ("purchase", "采购", (("orders", "采购订单"), ("receipts", "采购入库"),
                              ("returns", "采购退货"))),
    ("inventory", "库存", (("query", "库存查询"), ("movements", "库存流水"),
                               ("transfers", "仓库调拨"), ("stocktakes", "库存盘点"),
                               ("adjustments", "库存调整"))),
    ("production", "生产", (("plans", "生产计划"), ("orders", "生产订单"),
                             ("issues", "生产领料"), ("consumptions", "生产消耗"),
                             ("receipts", "生产入库"))),
    ("outsourcing", "委外", (("orders", "委外单"), ("issues", "委外发料"),
                                 ("receipts", "委外入库"))),
    ("reconciliation", "对账", (("customers", "客户对账"),
                                    ("suppliers", "供应商对账"),
                                    ("processors", "委外对账"),
                                    ("receipts", "收款记录"),
                                    ("payments", "付款记录"),
                                    ("month_end", "月末汇总"))),
    ("reports", "报表", (("sales", "销售报表"), ("purchase", "采购报表"),
                           ("inventory", "库存报表"), ("production", "生产报表"),
                           ("outsourcing", "委外报表"))),
    ("masterdata", "基础资料", (("items", "物料与产品"),
                                  ("categories", "物料与产品分类"),
                                  ("boms", "多级用料清单"),
                                  # 这一页只管单位：换算是全局的（单位的「基本单位 + 基本数量」），
                                  # 业务单位挂到物料所用基本单位下的那种。
                                  ("units", "计量单位"),
                                  ("customers", "客户"),
                                  ("suppliers", "供应商"),
                                  ("processors", "委外加工商"),
                                  ("warehouses", "仓库"))),
    ("system", "系统管理", (("organization", "组织管理"),
                              ("departments", "部门管理"), ("roles", "角色管理"),
                              ("users", "用户管理"), ("menus", "菜单列表"),
                              ("permissions", "权限配置"),
                              ("approvals", "审批配置"),
                              ("initialization", "数据初始化"),
                              ("audit_logs", "操作日志"))),
)


def seed_menus(db: Session) -> None:
    for group_order, (group_code, group_name, children) in enumerate(MENU_GROUPS, start=1):
        parent_id = db.execute(text("""
            INSERT INTO menus (code, name, path, sort_order) VALUES (:code, :name, :path, :sort_order)
            ON CONFLICT (code) DO NOTHING
            RETURNING id
        """), {"code": group_code, "name": group_name,
               "path": "/business-flow" if group_code == "business_flow" else None,
               "sort_order": group_order * 100}).scalar_one_or_none()
        if parent_id is None:
            parent_id = db.execute(text("SELECT id FROM menus WHERE code = :code"),
                                   {"code": group_code}).scalar_one()
        for child_order, (child_code, child_name) in enumerate(children, start=1):
            code = f"{group_code}.{child_code}"
            db.execute(text("""
                INSERT INTO menus (parent_id, code, name, path, sort_order)
                VALUES (:parent_id, :code, :name, :path, :sort_order)
                ON CONFLICT (code) DO NOTHING
            """), {"parent_id": parent_id, "code": code, "name": child_name,
                   "path": "/" + code.replace(".", "/"),
                   "sort_order": group_order * 100 + child_order})
