# PSI 进销存系统

项目地址：<https://github.com/dnmy-geo/PSI>

面向 10–100 人工厂的进销存管理系统，按销售订单生产与备货生产并存，替代纸质单据与 Excel 混合管理的现状。重点解决：销售订单到来时判断成品库存与生产缺料、盘点不便、月底对账耗时、责任划分不清晰。

系统是**前后端分离的模块化单体**：一套 React 前端、一套 FastAPI 后端、一个 PostgreSQL 数据库。销售、采购、库存、生产、委外、对账、报表、基础资料和系统管理在后端按模块划分，单据生效与库存、业务金额、审批状态的更新在同一个数据库事务内提交。

## 系统边界

明确**不做**以下内容：

- 不做 MES：没有工序、工艺路线、报工或工序进度管理；
- 不做库存批次管理，单据里的「分批入库」指多张业务单据，不是批次；
- 不计算生产成本或毛利，不生成总账凭证；对账金额是 PSI 业务口径，不是法定财务账；
- 生产模块只覆盖与库存有关的计划、订单、领料、消耗和产出入库。

## 功能范围

菜单预置 11 个一级分组、共 61 个菜单编码（工作台的三个子编码只作权限范围，不显示为导航项）：

| 一级菜单 | 覆盖内容 |
| --- | --- |
| 工作台 | 业务概览、我的审批待办、未发货／未入库／缺料提醒；提醒不占用库存 |
| 业务全景 | 按部门展示操作流程，节点跳转到有权限的业务页面 |
| 销售 | 销售订单（审批、强制结束）、销售出库（分批发货、退货补发）、销售退货 |
| 采购 | 采购订单（强制关闭）、采购入库（分次入库、原单补入）、采购退货 |
| 库存 | 库存查询、库存流水、仓库调拨、库存盘点（走审批）、库存调整（含盘点差异） |
| 生产 | 生产计划（多级缺料、按张数均分或手动拆单）、生产订单、生产领料、生产消耗、生产入库 |
| 委外 | 委外单（我方供料／加工商包料可混用）、委外发料、委外入库 |
| 对账 | 客户／供应商／委外加工商对账、收款记录、付款记录、月末汇总 |
| 报表 | 销售、采购、库存、生产、委外五类业务汇总 |
| 基础资料 | 物料与产品、分类、多级用料清单（BOM）、计量单位与换算、客户、供应商、委外加工商、仓库 |
| 系统管理 | 组织、部门、角色（岗位）、用户、菜单列表、权限配置、审批配置、数据初始化、操作日志 |

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 后端 | Python 3.13 · FastAPI · Pydantic 2 · SQLAlchemy 2（同步；全部手写 SQL，无 ORM 模型）· psycopg 3 · Alembic |
| 数据库 | PostgreSQL 18 |
| 前端 | React 18 · TypeScript 5.9（严格模式）· Vite 7 · React Router 7 · TanStack Query 5 |
| UI | Ant Design 5 · `@ant-design/pro-components` 2（ProLayout / ProTable / ProForm） |
| 认证 | 服务端会话表 + 不透明会话 ID 的安全 Cookie；写操作校验 CSRF 令牌；密码用 Argon2 哈希 |
| Excel | openpyxl（期初库存、期初往来、未完成业务接续的模板与导入） |
| 测试 | pytest + FastAPI TestClient（后端集成）· Vitest + Testing Library（前端组件） |
| 部署（规划） | Linux · Docker Compose · Nginx · HTTPS |

## 目录结构

```text
PSI/
├── server/                      FastAPI 后端
│   ├── app/
│   │   ├── main.py              应用入口，挂载各模块路由与 /api/health
│   │   ├── bootstrap.py         一次性初始化：组织、管理员、菜单、审批配置、三个预置仓库
│   │   ├── core/                本地 .env 加载、数据库会话、密码与 CSRF、分页、单据编号
│   │   ├── auth/                登录、注销、当前会话
│   │   ├── system/              组织、部门、角色、用户、菜单、岗位权限、操作日志、未完成业务接续
│   │   ├── approval/            审批配置、审批实例与待办
│   │   ├── masterdata/          计量单位、物料、分类、BOM、往来单位、仓库
│   │   ├── inventory/           结存、流水、统一过账、调拨、盘点、调整、期初库存
│   │   ├── sales/               销售订单、出库、退货
│   │   ├── purchase/            采购订单、入库、退货
│   │   ├── production/          生产计划、订单、领料、消耗、入库
│   │   ├── outsourcing/         委外单、发料、入库
│   │   ├── reconciliation/      期初往来、收付款记录、月末对账与明细
│   │   ├── reports/             五类业务汇总报表
│   │   └── workbench/           待办、概览、预警
│   ├── alembic/versions/        数据库迁移（0001 → 0020）
│   ├── tests/                   接口集成测试
│   ├── seed_injection_demo.py   注塑厂演示基础数据与单据头
│   ├── seed_injection_operations.py  演示数据的执行单据（入库、出库、领料、收付款、盘点等）
│   ├── .env.example             环境变量样例
│   └── README.md                后端接口清单与业务规则细则
├── web/                         React 前端
│   ├── src/
│   │   ├── main.tsx / root.tsx  入口、ProLayout 外壳、登录与会话
│   │   ├── api/client.ts        fetch 封装：Cookie、CSRF 令牌、X-Total-Count 分页
│   │   ├── components/          通用组件
│   │   │   ├── resource/        配置化页面引擎（ResourceConfig / FieldSpec 驱动 ProTable + ProForm）
│   │   │   ├── ApprovalProgress.tsx  单据详情里的审批进度
│   │   │   └── ListFilterBar.tsx     列表页筛选条
│   │   ├── pages/               页面
│   │   │   ├── registry.tsx     菜单编码 → 页面组件
│   │   │   ├── workbench/ report/ inventory/ business-flow/ organization/
│   │   │   └── special/         盘点、权限、审批配置、数据初始化等专门页面（每页一个文件）
│   │   ├── configs/             33 个常规列表／单据页面配置，按业务模块分文件
│   │   ├── actions/             列表行的专用动作（拆单、录入实盘数、重设密码…）
│   │   ├── utils/               关键词与日期筛选、整表分页拉取
│   │   ├── styles/              全局样式，按域拆分后由 index.css 统一引入
│   │   └── test/                Vitest 组件测试
│   └── README.md                前端运行与页面范围
```

## 快速开始

### 环境要求

- Python 3.13
- PostgreSQL 18（本地或可访问的实例）
- Node.js 20.19+ 或 22.12+（Vite 7 要求）
- [uv](https://docs.astral.sh/uv/)（可选，仓库带 `uv.lock`）

### 1. 准备数据库

创建空库，例如 `psi`。结构由 Alembic 迁移建立，不手工建表。

### 2. 启动后端

```bash
cd server

# 安装依赖（二选一，都会生成 server/.venv）
uv sync --extra dev               # 使用 uv.lock 的锁定版本
# python -m venv .venv && pip install -e ".[dev]"

source .venv/Scripts/activate     # Git Bash；PowerShell 用 .venv\Scripts\Activate.ps1

# 配置环境变量
cp .env.example .env              # PowerShell: Copy-Item .env.example .env
# 编辑 .env，把 PSI_DATABASE_URL 指向上一步的库：
#   PSI_DATABASE_URL=postgresql+psycopg://postgres:密码@localhost:5432/psi
#   PSI_COOKIE_SECURE=false       # 仅本地 HTTP 调试；生产经 HTTPS 时不要设置

# 建立表结构并初始化
alembic upgrade head
python -m app.bootstrap           # 需在 .env 或终端提供下面四个变量

# 启动 API
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`app.bootstrap` 只在数据库里还没有组织时可执行一次，它会创建组织、管理员岗位和账号，预置一二级菜单，为销售订单和盘点建好一级管理员审批配置，以及原材料仓、成品仓、现场仓三个仓库（之后可正常维护）。所需变量：

```dotenv
PSI_ORG_CODE=FACTORY
PSI_ORG_NAME=工厂
PSI_ADMIN_USERNAME=admin
PSI_ADMIN_PASSWORD=至少6位的管理员密码
```

终端里设置的同名环境变量优先于 `.env`。

### 3. 启动前端

```bash
cd web
npm install
npm run dev                       # http://127.0.0.1:5173/
```

Vite 把 `/api` 代理到 `http://127.0.0.1:8000`，Cookie 与 CSRF 令牌由 `src/api.ts` 统一处理，无需额外配置后端地址。

### 4. 可选：写入演示数据

```bash
cd server
.venv/Scripts/python.exe seed_injection_demo.py --org-code FACTORY        # 基础资料与单据头
.venv/Scripts/python.exe seed_injection_operations.py --org-code FACTORY  # 执行单据：入库、出库、领料、收付款、盘点
```

两个脚本都按单号幂等，重复执行不会重复插入；执行单据经应用服务层写入，库存与应收应付由统一过账服务生成。

## 常用命令

```bash
# 后端
uvicorn app.main:app --host 127.0.0.1 --port 8000   # 启动（在 server/ 下）
alembic upgrade head                                # 应用迁移
alembic revision -m "描述"                          # 新建迁移（结构变更一律加新迁移）
alembic current                                     # 当前数据库版本
python -m pytest -q                                 # 集成测试

# 前端
npm run dev                                         # 开发服务器 :5173
npm run build                                       # tsc 严格检查 + 生产构建
npm test                                            # Vitest 组件测试
```

`GET /api/health` 返回 `{"status": "ok", "database_revision": "<当前迁移版本>"}`，可用来同时确认服务与数据库版本。

## 关键设计约定

改动代码前需要了解的几条规则：

- **库存过账只有一个入口。** 采购入库、销售出库与退货、领料、消耗、生产入库、委外发料与入库、调拨、盘点差异、期初库存都走 `app/inventory/posting.py`。它负责锁定结存行、校验非负、更新余额并写库存流水，**不自行提交事务**——调用方必须把单据状态、库存变更和业务金额放进同一个事务。
- **禁止负库存。** 结存按「组织 + 仓库 + 物料」唯一；出库、消耗、调拨都不能让来源仓为负。盘点审批通过时若差额会造成负库存，该次审批不生效。
- **已生效单据不改写，改错走冲销。** 冲销保留原单、反向流水和原因，并记录操作人、时间与原因；有关联下游单据时按相反顺序先冲销下游。草稿才可直接修改或删除。
- **数量一律换算成基本单位。** 单据行保存输入单位、换算系数和基本单位数量；换算系数取自该单位在全局单位层级（两层）中挂到物料基本单位下的 `base_quantity`，找不到层级就拒绝保存。前端与后端传十进制字符串，Python 用 `Decimal`，数据库用 `numeric`。
- **生产数量是整数。** 生产计划与生产订单产出数量禁止小数；拆单后各单合计必须等于计划数量。多级缺料按「下级需求＝上级缺口×单位用量、下级缺口＝下级需求－该级现有库存，最低为 0」逐层展开，只把缺口往下传，不占用也不扣减库存，不计损耗。
- **一张生产订单只能有一张生产入库单**（数据库唯一约束）；委外入库则可以分批多张。
- **销售订单不占用库存。** 审批通过也不锁库存，只有实际出库才改变库存；已发＝累计出库－累计退货，未发＝订单数量－已发。退货不冲减应收，关联退货的补发不重复计入应收。
- **权限由后端逐项校验。** 岗位（角色）绑定菜单及动作权限，前端只据此控制按钮可见性，业务规则和状态流转一律以服务端为准。
- **分页计数只有一份过滤条件。** 新增列表接口用 `app/core/pagination.py` 的 `paginate(...)`，SQL 里不要写死 `LIMIT`/`OFFSET`，响应头返回精确总数 `X-Total-Count`。
- **单据编号可留空自动生成。** 销售、采购、生产、委外、盘点、调拨等单号留空时由 `app/core/document_numbers.py` 按「前缀＋日期＋四位流水」生成，按组织加锁取号。

## 数据库

结构全部由 Alembic 迁移管理（当前 head：`0020_outsourcing_numbers`）。迁移只建结构，不写业务数据；已执行的迁移不修改，变更一律新增迁移文件。

主要表分组：

- 基础资料与系统管理：`organizations`、`departments`、`roles`、`users`、`user_roles`、`auth_sessions`、`menus`、`role_permissions`、`approval_configs` / `approval_config_steps` / `approval_instances` / `approval_tasks`、`audit_logs`、`units`（全局两级换算层级）、`item_categories`、`items`、`bom_headers` / `bom_lines`、`parties`、`warehouses`
- 库存核心：`stock_balances`（结存）、`stock_movements`（不可改写的流水）、调拨、调整、盘点、期初库存
- 业务单据：销售订单／出库／退货、采购订单／入库／退货、生产计划／订单／领料／消耗／入库、委外单／发料／入库
- 对账：`business_amount_entries`（业务金额流水）、`cash_records`、`party_opening_balances`、`carryover_documents` / `carryover_lines`（未完成业务接续）

## 测试

### 后端

集成测试跑在**独立的已迁移测试库**上，不要指向开发库：

```bash
cd server
PSI_DATABASE_URL="postgresql+psycopg://postgres:密码@localhost:5432/psi_test" \
  .venv/Scripts/python.exe -m pytest -q
```

测试数据在外层事务里回滚，不会留下组织、账号或仓库记录。首次使用 `psi_test` 前先对它执行一次 `alembic upgrade head`。不设 `PSI_DATABASE_URL` 时会退回 `server/.env` 的开发库，可能报「Organization already exists」或列不存在的错误——那是库选错了，不是代码问题。

也可以临时建一个一次性库来跑，完全不碰现有数据库（需要建库权限，在 `server/` 下执行）：

```bash
.venv/Scripts/python.exe tests/run_production_isolated.py tests/test_sales_fulfillment_api.py
```

### 前端

```bash
cd web
npm test                    # Vitest 组件测试
npm run build               # TypeScript 严格检查 + 生产构建
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [server/README.md](server/README.md) | 完整接口清单、业务规则细则（退货上限、冲销顺序、盘点流程等） |
| [web/README.md](web/README.md) | 前端运行方式与页面范围 |

## 部署要点

- 前端构建产物与 `/api` 部署在**同一个 HTTPS 站点**，由 Nginx 提供静态文件并反向代理后端；后端不配置 CORS，只接受同源请求（开发时由 Vite 代理解决），数据库端口不对普通用户开放。
- 生产环境保持 Cookie 的 `Secure` 属性（默认开启），仅在本地 HTTP 调试时才设置 `PSI_COOKIE_SECURE=false`。
- 配置与密码由环境变量提供，不写入代码库（`.env` 已在忽略规则中）。
- 数据库每日备份并保存到服务器之外的另一处存储，定期做恢复演练；结构变更用 Alembic 顺序执行。

## 当前状态

前后端已覆盖全部预置菜单，销售、采购、库存、生产、委外、对账的核心流程及其后端集成测试均已实现并跑通。尚未完成的是**用真实岗位和上线数据做的现场端到端验收**，以及期初库存、未完成业务和期初往来的实际数据核对；报表指标仍待业务最终确认。

## 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源，版权所有 © 2026 智创新途-石生。

- 可自由使用、修改和分发，包括商业用途；
- 分发时需保留 [LICENSE](LICENSE) 与版权声明，被修改的文件需标注改动；
- 软件按「原样」提供，不含任何明示或默示担保。
