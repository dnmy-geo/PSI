import { afterEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import { BrowserRouter } from 'react-router-dom';
import { Root } from '../root';

afterEach(() => vi.unstubAllGlobals());

it('logs in and renders the authorized workbench menu', async () => {
  const calls: string[] = [];
  let loginBody: Record<string, unknown> | null = null;
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    calls.push(path);
    let status = 200;
    let body: unknown = {};
    if (path === '/api/auth/me') { status = 401; body = { detail: 'authentication required' }; }
    if (path === '/api/auth/login') {
      loginBody = JSON.parse(String(init?.body));
      body = { user_id: 'user-1', organization_id: 'org-1', username: 'admin', display_name: '管理员', csrf_token: 'csrf' };
    }
    if (path === '/api/system/my-menus') body = [
      { id: 'parent', parent_id: null, code: 'workbench', name: '工作台', path: null },
      { id: 'child', parent_id: 'parent', code: 'workbench.overview', name: '业务概览', path: '/workbench/overview' },
      { id: 'tasks', parent_id: 'parent', code: 'workbench.tasks', name: '我的待办', path: '/workbench/tasks' },
      { id: 'alerts', parent_id: 'parent', code: 'workbench.alerts', name: '预警提醒', path: '/workbench/alerts' },
      { id: 'flow', parent_id: null, code: 'business_flow', name: '业务全景', path: '/business-flow' },
      { id: 'sales', parent_id: null, code: 'sales', name: '销售', path: null },
      { id: 'sales-orders', parent_id: 'sales', code: 'sales.orders', name: '销售订单', path: '/sales/orders' },
      { id: 'production', parent_id: null, code: 'production', name: '生产', path: null },
      { id: 'production-plans', parent_id: 'production', code: 'production.plans', name: '生产计划', path: '/production/plans' },
      { id: 'production-orders', parent_id: 'production', code: 'production.orders', name: '生产订单', path: '/production/orders' },
      { id: 'production-issues', parent_id: 'production', code: 'production.issues', name: '生产领料', path: '/production/issues' },
      { id: 'production-consumptions', parent_id: 'production', code: 'production.consumptions', name: '生产消耗', path: '/production/consumptions' },
      { id: 'production-receipts', parent_id: 'production', code: 'production.receipts', name: '生产入库', path: '/production/receipts' },
    ];
    if (path.startsWith('/api/approval/tasks/mine') || path === '/api/workbench/alerts') body = [];
    if (path === '/api/workbench/overview') body = {
      pending_my_approvals: 0, approved_sales_orders: 0, open_purchase_orders: 0,
      open_production_plans: 0, open_production_orders: 0, open_outsourcing_orders: 0,
      counting_stocktakes: 0,
    };
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  }));
  window.history.replaceState({}, '', '/');
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}><BrowserRouter><Root /></BrowserRouter></QueryClientProvider></AntApp></ConfigProvider>);
  expect(await screen.findByText('工厂业务协同平台')).toBeInTheDocument();
  expect(screen.queryByLabelText('组织编码')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'admin' } });
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'TestOnlyPassword123!' } });
  fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));
  await waitFor(() => expect(calls).toContain('/api/workbench/overview'), { timeout: 10_000 });
  expect(loginBody).toEqual({ username: 'admin', password: 'TestOnlyPassword123!' });
  expect(await screen.findByText('我的待审批')).toBeInTheDocument();
  const sidebar = document.querySelector('.ant-pro-sider');
  expect(sidebar).not.toBeNull();
  expect(within(sidebar as HTMLElement).getByText('工作台')).toBeInTheDocument();
  expect(within(sidebar as HTMLElement).queryByText('业务概览')).not.toBeInTheDocument();
  expect(within(sidebar as HTMLElement).queryByText('我的待办')).not.toBeInTheDocument();
  fireEvent.click(within(sidebar as HTMLElement).getByText('生产'));
  expect(within(sidebar as HTMLElement).getByText('生产领料')).toBeInTheDocument();
  expect(within(sidebar as HTMLElement).getByText('生产消耗')).toBeInTheDocument();
  expect(within(sidebar as HTMLElement).getByText('生产入库')).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: '我的待办' })).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: '预警提醒' })).toBeInTheDocument();
  fireEvent.click(within(sidebar as HTMLElement).getByText('业务全景'));
  expect(await screen.findByRole('heading', { name: '从部门视角，看清每一步业务。' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '进入销售订单' })).toHaveAttribute('href', '/sales/orders');
  expect(screen.getByRole('link', { name: '进入销售订单完成' })).toHaveAttribute('href', '/sales/orders');
  expect(screen.getAllByText('暂无权限').length).toBeGreaterThan(0);
  expect(document.querySelectorAll('.business-flow-lines path[marker-end]')).toHaveLength(5);
  expect(document.querySelectorAll('.business-flow-lines path[stroke-dasharray]')).toHaveLength(1);
  expect(document.querySelectorAll('.business-flow-junction')).toHaveLength(1);
  expect([...document.querySelectorAll('.business-flow-lines path[marker-end]')].every((path) =>
    (path.getAttribute('d')?.match(/ C /g) ?? []).length === 1)).toBe(true);
  for (const [department, expected] of [
    ['采购部门', '采购订单'], ['仓库部门', '库存查询'], ['生产部门', '生产计划'],
    ['委外部门', '委外单'], ['财务部门', '客户对账'],
  ]) {
    fireEvent.click(screen.getByRole('button', { name: new RegExp(department) }));
    const diagram = screen.getByRole('region', { name: `${department}操作流程` });
    expect(within(diagram).getByText(expected)).toBeInTheDocument();
    expect(within(diagram).queryByText('销售订单')).not.toBeInTheDocument();
    expect(within(diagram).queryByText('销售订单完成')).not.toBeInTheDocument();
    if (department === '生产部门') {
      expect(within(diagram).getByText('生产入库')).toBeInTheDocument();
      expect(within(diagram).getByRole('link', { name: '进入生产入库' }))
        .toHaveAttribute('href', '/production/receipts');
    }
  }
}, 20_000);
