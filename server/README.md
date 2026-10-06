# PSI 后端数据库迁移

`0003_business_flow_menu` 为已有数据库增加「业务全景」一级菜单；`0004_production_documents_menus` 增加生产领料、生产消耗和生产入库菜单，并复制现有生产订单岗位权限。新数据库由初始化流程预置这些菜单。

初始结构在 `alembic/versions/0001_initial.sql`，由同名 Alembic 修订执行；`0002_reconciliation_accounts` 将供应商与加工商的期初及付款账户分开。当前已实现 FastAPI 基础接口、登录会话、组织与部门及岗位和用户维护、菜单与岗位权限配置、销售订单审批与出退库、采购订单与分批入库及部分退货、仓库与物料基础资料、物料分类、往来单位、BOM 版本维护、库存流水查询、仓库调拨、期初库存 Excel 导入、盘点审批、手工库存调整及统一库存过账服务。生产计划、缺料、拆单、订单、领料、消耗和入库，委外单、我方发料和分次委外入库，以及期初往来、收付款和月末对账接口已实现。

本地执行方式：

1. 创建 Python 3.13 虚拟环境并安装 `pyproject.toml` 中的依赖。
2. 在 `server/.env` 配置 `PSI_DATABASE_URL`，形式为 `postgresql+psycopg://用户名:密码@localhost:5432/psi`。可参考 `.env.example`；本地 `.env` 已加入忽略规则，不应提交。终端里设置的同名环境变量优先于 `.env`。
3. 在 `server` 目录运行 `alembic upgrade head`。
4. 用 `alembic current` 和 PostgreSQL 表清单确认迁移结果。

迁移只创建结构。第一次初始化时，在 `server/.env` 或当前终端设置 `PSI_DATABASE_URL`、`PSI_ORG_CODE`、`PSI_ORG_NAME`、`PSI_ADMIN_USERNAME`、`PSI_ADMIN_PASSWORD`，然后运行 `python -m app.bootstrap`。管理员密码至少 6 个字符。此命令仅在数据库中尚无组织时可运行，创建组织、管理员岗位和账号，预置一二级菜单、销售订单及盘点的一级管理员审批配置，以及原材料仓、成品仓、现场仓；这些仓库以后可通过接口维护。

运行 `uvicorn app.main:app --host 127.0.0.1 --port 8000` 启动 API。生产环境应经 HTTPS 反向代理访问，Cookie 默认带 `Secure` 属性；仅在本地 HTTP 调试时才设置 `PSI_COOKIE_SECURE=false`。该设置也可写在 `server/.env` 中。

需要注塑厂演示数据时，在已初始化的本地数据库执行 `.venv/Scripts/python.exe seed_injection_demo.py --org-code FACTORY`。脚本创建带 `DEMO-` 前缀的分类、物料、往来单位、BOM、期初库存及采购、销售、生产和委外单据；重复执行不会重复插入，也不会覆盖已有记录。

`seed_injection_demo.py` 只建到单据头，业务都停在「下了单、没执行」。再执行 `.venv/Scripts/python.exe seed_injection_operations.py --org-code FACTORY` 可补齐执行单据：采购分批入库、销售订单审批与分批出库（含退货和补发）、生产领料与消耗与入库、委外发料与入库、收付款与期初往来，以及一次月末盘点及其盘盈亏调整。该脚本同样按单号幂等。它经应用的服务层写单据，库存与应收应付由 `app/inventory/posting.py` 和各自的服务生成，不使用原生 SQL 改动结存。

现有接口：

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/health` | 数据库连通性与迁移版本 |
| `GET /api/workbench/tasks`、`/overview`、`/alerts` | 我的审批待办、业务概览与未发货／未入库／缺料提醒；提醒不预留库存 |
| `POST /api/auth/login` | 以用户名和密码登录，获得安全 Cookie 与 CSRF 令牌；旧客户端可选传组织编码，同名账号跨组织重复时必须传组织编码 |
| `GET /api/auth/me` | 获取当前账号和 CSRF 令牌 |
| `POST /api/auth/logout` | 注销当前会话 |
| `GET /api/warehouses` | 查询本组织仓库 |
| `POST /api/warehouses` | 有仓库新增权限的岗位新增仓库 |
| `PUT /api/warehouses/{id}` | 有仓库修改权限的岗位修改编码、名称及启停状态 |
| `DELETE /api/warehouses/{id}` | 有仓库删除权限的岗位删除无业务引用的仓库 |
| `GET/POST /api/units`、`GET/PUT/DELETE /api/units/{id}` | 计量单位查询、新增、编辑、停用与删除；单位的 `base_unit_id` + `base_quantity` 构成全局换算层级（1 业务单位 = N 基本单位），只允许两层 |
| `GET/POST /api/items`、`PUT/DELETE /api/items/{id}` | 物料和产品查询、新增、编辑、停用与删除 |
| `GET /api/items/{id}` | 查看单个物料 |
| `GET/POST /api/item-categories`、`GET/PUT/DELETE /api/item-categories/{id}` | 物料分类树维护；禁止循环引用 |
| `GET/POST /api/parties`、`GET/PUT/DELETE /api/parties/{id}` | 客户、供应商、加工商共用往来单位维护；支持多身份 |
| `GET/POST /api/boms`、`GET/PUT/DELETE /api/boms/{id}`、`POST /api/boms/{id}/activate` | BOM 版本维护与启用；一个物料只能启用一个版本，禁止循环引用 |
| `GET /api/inventory/balances` | 查询本组织库存，可按仓库筛选 |
| `GET /api/inventory/movements` | 按仓库、物料和过账时间查询本组织库存流水；分页返回来源单据和操作人 |
| `GET /api/inventory/transfers` | 按状态分页查询调拨单 |
| `POST /api/inventory/transfers` | 创建仓库调拨草稿，保存单位换算快照 |
| `GET /api/inventory/transfers/{id}` | 查看调拨单及明细 |
| `POST /api/inventory/transfers/{id}/post` | 调拨过账；库存不足时整单不生效 |
| `POST /api/inventory/transfers/{id}/reverse` | 按原因冲销已过账调拨，保留反向流水 |
| `GET /api/inventory/opening-stock/template` | 下载期初库存 Excel 模板 |
| `GET /api/inventory/opening-stock` | 按状态分页查询期初库存单 |
| `POST /api/inventory/opening-stock/import` | 上传 Excel，校验并保存期初库存草稿 |
| `GET /api/inventory/opening-stock/{id}` | 查看期初库存草稿及换算结果 |
| `POST /api/inventory/opening-stock/{id}/post` | 确认期初库存并写入库存流水 |
| `POST /api/inventory/opening-stock/{id}/reverse` | 按原因冲销期初库存；更正后的数量可用库存调整单登记 |
| `GET/POST /api/inventory/stocktakes`、`GET /api/inventory/stocktakes/{id}` | 查询、创建盘点单 |
| `POST /api/inventory/stocktakes/{id}/start`、`PUT /api/inventory/stocktakes/{id}/counts` | 记录截止账面数并暂停该仓过账，录入实盘数；驳回后可重新开始 |
| `POST /api/inventory/stocktakes/{id}/submit`、`POST /api/inventory/stocktakes/{id}/cancel` | 提交盘点审批并恢复仓库过账，或备注取消未提交的盘点 |
| `GET/POST /api/inventory/adjustments`、`GET/PUT/DELETE /api/inventory/adjustments/{id}` | 查询与维护手工库存调整草稿，亦可查询盘点自动产生的调整单 |
| `POST /api/inventory/adjustments/{id}/post`、`POST /api/inventory/adjustments/{id}/reverse` | 授权调整库存；已过账调整按原因冲销并保留反向流水 |
| `GET/PUT /api/system/organization` | 查看和修改当前组织名称 |
| `GET/POST /api/system/departments`、`GET/PUT/DELETE /api/system/departments/{id}` | 部门层级维护；新建时编码留空自动生成 `DEP-0001` 等；防循环与跨组织引用 |
| `GET/POST /api/system/roles`、`GET/PUT/DELETE /api/system/roles/{id}` | 岗位角色维护；保护系统管理员岗位 |
| `GET/POST /api/system/users`、`GET/PUT/DELETE /api/system/users/{id}` | 账号、所属部门和角色维护；删除操作为停用 |
| `POST /api/system/users/{id}/reset-password` | 管理员重设密码并撤销原会话 |
| `GET/POST /api/system/menus`、`GET/PUT/DELETE /api/system/menus/{id}` | 全局一二级菜单目录维护；系统管理员操作 |
| `GET /api/system/my-menus` | 当前用户可见菜单，自动带出上级菜单 |
| `GET /api/system/my-permissions` | 当前用户在各菜单可执行的动作权限，供前端控制按钮可见性 |
| `GET/PUT /api/system/roles/{id}/permissions` | 查询或整体替换岗位菜单及操作权限 |
| `GET /api/system/audit-logs` | 按操作人、单据、操作和时间查询本组织审计日志 |
| `GET /api/approval/configs`、`GET/PUT /api/approval/configs/{document_type}` | 审批配置查询与保存；支持销售订单和盘点，每级指定岗位或用户 |
| `GET /api/approval/tasks/mine`、`POST /api/approval/tasks/{id}/decision` | 查询当前步骤待办，并逐级同意或驳回销售订单；拒绝须填写意见 |
| `GET /api/approval/instances/{id}`、`GET /api/approval/documents/{type}/{id}/instances` | 按权限查看审批实例与历史步骤 |
| `GET/POST /api/sales/orders`、`GET/PUT/DELETE /api/sales/orders/{id}` | 销售订单草稿、查询、修改与删除；订单行保存单位换算和金额 |
| `POST /api/sales/orders/{id}/submit` | 提交销售订单审批并冻结当前审批步骤快照 |
| `POST /api/sales/orders/{id}/close` | 已审批订单备注强制结束 |
| `GET/POST /api/sales/shipments`、`GET/PUT/DELETE /api/sales/shipments/{id}` | 销售出库草稿、查询、修改与删除；普通发货或关联退货的补发 |
| `POST /api/sales/shipments/{id}/post` | 出库过账并扣库存；普通发货形成应收，补发不重复计入 |
| `POST /api/sales/shipments/{id}/reverse` | 冲销普通发货或补发；普通发货同步冲回应收 |
| `GET/POST /api/sales/returns`、`GET/PUT/DELETE /api/sales/returns/{id}` | 销售退货草稿、查询、修改与删除 |
| `POST /api/sales/returns/{id}/post` | 部分或全部退货过账；增加目标仓库存并更新订单净已发数量，不冲减应收 |
| `POST /api/sales/returns/{id}/reverse` | 冲销销售退货；有已补发时先冲销补发 |
| `GET/POST /api/purchase/orders`、`GET/PUT/DELETE /api/purchase/orders/{id}` | 采购订单草稿、查询、修改与删除 |
| `POST /api/purchase/orders/{id}/open`、`POST /api/purchase/orders/{id}/close` | 打开采购订单；填写备注后强制关闭 |
| `GET/POST /api/purchase/receipts`、`GET/PUT/DELETE /api/purchase/receipts/{id}` | 分批采购入库草稿维护与查询 |
| `POST /api/purchase/receipts/{id}/post` | 按原订单未入库数量过账，增加库存与供应商应付业务额 |
| `POST /api/purchase/receipts/{id}/reverse` | 冲销采购入库；有有效退货时先冲销退货 |
| `GET/POST /api/purchase/returns`、`GET/PUT/DELETE /api/purchase/returns/{id}` | 对已入库货品建立部分或全部退货单 |
| `POST /api/purchase/returns/{id}/post` | 扣减来源仓库存及应付业务额，并增加原采购订单未入库数量 |
| `POST /api/purchase/returns/{id}/reverse` | 冲销采购退货；若释放的采购缺口已被后续补入占用，先冲销后续入库 |
| `GET/POST /api/production/plans`、`GET/PUT/DELETE /api/production/plans/{id}` | 生产计划维护与查询；计划数量为整数 |
| `POST /api/production/plans/{id}/open`、`POST /api/production/plans/{id}/close` | 开始或结束生产计划 |
| `GET /api/production/plans/{id}/shortage` | 多级 BOM 向下计算缺料，汇总需求后逐级抵扣现有库存 |
| `POST /api/production/plans/{id}/split/auto`、`POST /api/production/plans/{id}/split/manual` | 按订单数均分或手工拆分生产订单，总量保持不变 |
| `GET /api/production/orders`、`GET /api/production/orders/{id}`、`POST /api/production/orders/{id}/open`、`DELETE /api/production/orders/{id}` | 生产订单查询、开单与删除；只有已冲销领料引用时保留取消历史并释放计划数量 |
| `GET/POST /api/production/issues`、`GET/PUT/DELETE /api/production/issues/{id}`、`POST /api/production/issues/{id}/post`、`POST /api/production/issues/{id}/reverse` | 生产领料在仓库间调拨；已过账领料可填写原因冲销 |
| `GET/POST /api/production/consumptions`、`GET/PUT/DELETE /api/production/consumptions/{id}`、`POST /api/production/consumptions/{id}/post` | 随时登记实际消耗并扣减库存 |
| `POST /api/production/consumptions/{id}/reverse` | 冲销实际消耗；已生产入库时先冲销入库 |
| `GET/POST /api/production/receipts`、`GET/PUT/DELETE /api/production/receipts/{id}`、`POST /api/production/receipts/{id}/post` | 每张生产订单唯一一张生产入库单，可同时包含半成品和成品 |
| `POST /api/production/receipts/{id}/reverse` | 冲销生产入库，恢复订单为可冲销状态；冲销后取消原订单再拆新订单 |
| `GET/POST /api/outsourcing/orders`、`GET/PUT/DELETE /api/outsourcing/orders/{id}`、`POST /api/outsourcing/orders/{id}/open`、`POST /api/outsourcing/orders/{id}/close` | 委外单维护，材料逐行区分我方供料或加工商包料，备注关闭 |
| `GET/POST /api/outsourcing/issues`、`GET/PUT/DELETE /api/outsourcing/issues/{id}`、`POST /api/outsourcing/issues/{id}/post`、`POST /api/outsourcing/issues/{id}/reverse` | 我方委外发料直接扣来源仓库存；先冲销下游入库，再冲销发料 |
| `GET/POST /api/outsourcing/receipts`、`GET/PUT/DELETE /api/outsourcing/receipts/{id}`、`POST /api/outsourcing/receipts/{id}/post`、`POST /api/outsourcing/receipts/{id}/reverse` | 多张委外入库单分批入库并形成加工商应付；冲销同步反向过账库存与应付 |
| `GET/POST /api/reconciliation/opening-balances`、`PUT/DELETE /api/reconciliation/opening-balances/{id}` | 按客户、供应商或加工商账户维护期初往来余额 |
| `GET/POST /api/reconciliation/cash-records`、`GET/PUT/DELETE /api/reconciliation/cash-records/{id}` | 登记客户收款、供应商或加工商付款；可选关联对应业务订单 |
| `GET /api/reconciliation/month-end` | 按月份和账户类型查看各往来单位期初、本月业务额、收付款和期末余额 |
| `GET /api/reconciliation/{account_type}/parties/{party_id}/statement` | 查看单个往来单位当月业务金额流水和收付款明细 |
| `GET /api/reports/sales`、`/purchase`、`/inventory`、`/production`、`/outsourcing` | 按 `date_from`、`date_to` 查询基础业务汇总；数量逐物料按基本单位展示，库存报表另按仓库分组 |

所有分页列表接口在响应头里返回精确总数 `X-Total-Count`。新增列表接口时请用 `app/core/pagination.py` 的 `paginate(db, query, params, limit=…, offset=…, response=…)`：它把同一段 SQL 和同一份参数包成子查询计数，过滤条件只有一份，不会出现"列表过滤了、计数没过滤"。SQL 里不要写死 `LIMIT`/`OFFSET`，由它追加。计数子查询里用 `CAST(:param AS 类型) IS NULL` 而不是裸 `:param IS NULL`，否则 PostgreSQL 推断不出参数类型。

除登录和健康检查外，接口均要求会话 Cookie；写操作还要求 `X-CSRF-Token` 请求头。业务与基础资料接口按岗位的菜单动作授权；组织、部门、角色、用户、菜单和权限治理仍限 `system_admin`。仓库与系统管理写操作记录审计日志，停用有结存的仓库或删除已有业务引用的仓库会被拒绝。不能停用或移除最后一个有效管理员账号。菜单目录存于全局 `menus` 表，岗位授权按组织隔离；非查看操作需要同时授权该菜单的查看权限。

审批配置保存时会校验审批岗位或用户属于当前组织且可用；启用的审批岗位至少要有一位有效成员。每次保存版本递增，未来发起的审批使用新配置。提交时复制审批步骤，配置修改不改变已提交实例。审批任务要求既是本步骤配置的审批人，也拥有对应单据菜单的 `approve` 岗位权限；最终同意或驳回与单据状态在同一事务中更新。销售订单不占用库存，草稿或驳回后可修改，只有已审批订单可备注强制结束。盘点开始时保存仓库账面数并暂停该仓过账；提交后恢复过账。最终审批同意时按截止账面数与实盘数的差额调整当前库存，若造成负库存则审批不生效。驳回后重新开始盘点会重新记录截止账面数。

销售出库、退货以草稿创建，过账时重新核对来源数量和状态；重复过账不会重复扣增库存。普通出库累计量不得超过原订单数量，关联退货的补发累计量不得超过该退货行数量；退货累计量不得超过原出库行数量。普通出库按原订单价格形成业务应收，分批发货的金额按累计数量计算并在最后一批对齐订单行金额。退货和补发均不改变应收。已过账单据不可直接修改或删除；冲销会保留原单、反向流水与原因。

采购订单无需审批，草稿打开后可分次入库；入库前筛掉的货品不填入系统，不另设验收环节。入库过账以净已入库量校验上限，因此已过账退货释放的缺口可以继续从原采购订单入库。采购退货须关联原入库行，累计退货不能超过该行入库数量，来源仓库存也必须足够。采购业务应付额按入库增加、退货减少；重复过账不重复记账。关闭采购订单须填写备注，关闭后不能继续入库；已过账单据冲销同步反向登记库存和业务应付额。

`app/inventory/posting.py` 是单据服务调用的库存过账入口，负责锁定仓库与结存、校验非负、更新余额并写库存流水。它不自行提交事务；调用方需把单据状态、库存变更和业务金额放在同一事务中提交。当前没有向用户开放单独修改库存的通用接口。

期初库存模板列名固定为“仓库编码、物料编码、单位编码、数量”，一份文件最多 5000 条有效记录。上传只生成草稿，不改变库存；确认过账时同一仓库与物料如果已有库存流水则拒绝再次作为期初导入。调拨和期初都将输入单位换算成基本单位，并保存原输入及换算系数。单据行填的单位若就是物料的基本单位，系数为 1；否则该单位必须直接挂在物料的基本单位之下（全局单位层级），取其 `base_quantity` 作为系数，找不到这样的层级就拒绝保存。已经产生引用的基础资料通常应停用而非删除；物料仍有结存时不可停用。物料类型和基本单位创建后保持不变，避免历史库存单位含义改变。

运行 `python -m pytest -q` 可对已迁移的 PostgreSQL 数据库执行接口集成测试。测试数据在外层事务中回滚，不会留下组织、账号或仓库记录。
