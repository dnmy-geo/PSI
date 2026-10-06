# PSI 前端

采用 React 18、TypeScript、Vite、Ant Design 5 和 `@ant-design/pro-components` 2，组件选用参考 [Pro Components 文档](https://pro-components.antdigital.dev/)。菜单布局使用 ProLayout；业务列表、表单和详情主要使用 ProTable、ProForm、PageContainer 与 Ant Design 组件。路由由 React Router 处理，接口缓存与刷新使用 TanStack Query。

## 本地运行

1. 在 `server` 目录启动已迁移、已初始化组织和管理员的 FastAPI：`uvicorn app.main:app --host 127.0.0.1 --port 8000`。仅本地 HTTP 调试时设置 `PSI_COOKIE_SECURE=false`。
2. 在 `web` 目录运行 `npm install`、`npm run dev`，访问 `http://127.0.0.1:5173/`。
3. Vite 将 `/api` 代理到 `http://127.0.0.1:8000`，登录 Cookie 与 CSRF 令牌由前端请求封装处理。

`npm run build` 做 TypeScript 检查和生产构建，`npm test` 做组件交互测试。正式部署时应让静态文件与 `/api` 位于同一 HTTPS 站点。

## 页面范围

当前已覆盖系统预置的全部一级、二级菜单：工作台、销售、采购、库存、生产、委外、对账、报表、基础资料和系统管理。常规资料与业务单据使用配置化 ProTable + ProForm；生产计划拆单、库存盘点、期初 Excel、审批配置、岗位权限、月末对账采用专门页面。页面动作仍由后端岗位权限和单据状态校验。

报表最终指标仍依赖业务确认。桌面浏览器视觉走查和完整用户操作验收仍需在可用浏览器环境中完成；当前验证覆盖构建、组件测试，以及通过本地 Vite 代理连接独立测试数据库的 API 链路。
