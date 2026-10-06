import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import { setCsrfToken } from '../api/client';
import { resources } from '../configs';
import { ResourcePage } from '../components/resource';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setCsrfToken(''); });

it('creates a warehouse through ProTable and ProForm with CSRF', async () => {
  let submitted: Record<string, unknown> | null = null;
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === '/api/warehouses' && init?.method === 'POST') {
      submitted = JSON.parse(String(init.body));
      expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('test-csrf');
      return new Response(JSON.stringify({ id: 'warehouse-1', ...submitted }), { status: 201, headers: { 'Content-Type': 'application/json' } });
    }
    const body = path === '/api/system/my-permissions' ? { 'masterdata.warehouses': ['view', 'create', 'update', 'delete'] } : [];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  setCsrfToken('test-csrf');
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <ResourcePage config={resources['masterdata.warehouses']} />
  </QueryClientProvider></AntApp></ConfigProvider>);
  fireEvent.click(await screen.findByRole('button', { name: /新建仓库/ }));
  const dialog = (await screen.findAllByRole('dialog')).at(-1)!;
  expect(within(dialog).getByRole('region', { name: '基本信息' })).toBeInTheDocument();
  fireEvent.change(withinDialog(dialog, '仓库编码'), { target: { value: 'EXTRA' } });
  fireEvent.change(withinDialog(dialog, '仓库名称'), { target: { value: '备用仓' } });
  fireEvent.click(within(dialog).getByRole('button', { name: /确\s*定/ }));
  await waitFor(() => expect(submitted).toMatchObject({ code: 'EXTRA', name: '备用仓' }));
});

it('shows an automatic sales number and one-row detail layout', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    const body = path === '/api/system/my-permissions'
      ? { 'sales.orders': ['view', 'create'] } : [];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <ResourcePage config={resources['sales.orders']} />
  </QueryClientProvider></AntApp></ConfigProvider>);
  fireEvent.click(await screen.findByRole('button', { name: /新建销售订单/ }));
  const dialog = (await screen.findAllByRole('dialog')).at(-1)!;
  expect(within(dialog).getByText('XS年月日流水号')).toBeInTheDocument();
  expect(within(dialog).queryByRole('textbox', { name: '单号' })).not.toBeInTheDocument();
  const details = within(dialog).getByRole('region', { name: '订单明细' });
  expect(details).toHaveClass('is-inline-lines');
});

it('filters a paged list beyond the first visible page', async () => {
  const orders = Array.from({ length: 12 }, (_, index) => ({ id: `order-${index + 1}`, document_no: `SO-${index + 1}` }));
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    const body = url.pathname === '/api/system/my-permissions' ? {}
      : url.pathname === '/api/sales/orders' ? orders.slice(Number(url.searchParams.get('offset') ?? 0),
        Number(url.searchParams.get('offset') ?? 0) + Number(url.searchParams.get('limit') ?? 100)) : [];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <ResourcePage config={{ title: '销售订单', endpoint: '/api/sales/orders', menuCode: 'sales.orders',
      columns: [{ key: 'document_no', title: '单号' }], serverPaging: true }} />
  </QueryClientProvider></AntApp></ConfigProvider>);
  expect(await screen.findByText('SO-1')).toBeInTheDocument();
  expect(screen.queryByText('SO-12')).not.toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText('请输入关键词'), { target: { value: 'SO-12' } });
  fireEvent.click(screen.getByRole('button', { name: /查\s*询/ }));
  expect(await screen.findByText('SO-12')).toBeInTheDocument();
  expect(screen.queryByText('SO-1')).not.toBeInTheDocument();
});

it('copies the selected purchase order line into a receipt draft', async () => {
  let submitted: Record<string, unknown> | null = null;
  const orderId = '11111111-1111-4111-8111-111111111111';
  const lineId = '22222222-2222-4222-8222-222222222222';
  const itemId = '33333333-3333-4333-8333-333333333333';
  const unitId = '44444444-4444-4444-8444-444444444444';
  const warehouseId = '55555555-5555-4555-8555-555555555555';
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === '/api/purchase/receipts' && init?.method === 'POST') {
      submitted = JSON.parse(String(init.body));
      return new Response(JSON.stringify({ id: 'receipt-1', ...submitted }), { status: 201, headers: { 'Content-Type': 'application/json' } });
    }
    let body: unknown = [];
    if (path === '/api/system/my-permissions') body = { 'purchase.receipts': ['view', 'create'] };
    // 入库单的订单下拉只列「进行中且还有未入库量」的订单，mock 也按这个形状给。
    if (path.startsWith('/api/purchase/orders?')) body = [{ id: orderId, document_no: 'PO-1', status: 'open',
      lines: [{ id: lineId, item_id: itemId, unit_id: unitId, quantity: 10, unreceived_quantity_base: 10 }] }];
    if (path === `/api/purchase/orders/${orderId}`) body = { id: orderId, lines: [{ id: lineId, item_id: itemId, unit_id: unitId, quantity: 10 }] };
    if (path === '/api/items') body = [{ id: itemId, code: 'MAT-1', name: '原料' }];
    if (path === '/api/units') body = [{ id: unitId, code: 'PCS', name: '个' }];
    if (path === '/api/warehouses') body = [{ id: warehouseId, code: 'RAW', name: '原材料仓' }];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <ResourcePage config={resources['purchase.receipts']} />
  </QueryClientProvider></AntApp></ConfigProvider>);
  fireEvent.click(await screen.findByRole('button', { name: /新建采购入库/ }));
  const dialog = (await screen.findAllByRole('dialog')).at(-1)!;
  expect(within(dialog).getByRole('region', { name: '基本信息' })).toBeInTheDocument();
  expect(within(dialog).getByRole('region', { name: '入库明细' })).toBeInTheDocument();
  fireEvent.change(withinDialog(dialog, '单号'), { target: { value: 'PR-1' } });
  fireEvent.mouseDown(withinDialog(dialog, '采购订单'));
  fireEvent.click(await screen.findByText('PO-1'));
  fireEvent.mouseDown(withinDialog(dialog, '入库仓库'));
  fireEvent.click(await screen.findByText('RAW · 原材料仓'));
  fireEvent.click(screen.getByRole('button', { name: /添加入库明细/ }));
  fireEvent.mouseDown(withinDialog(dialog, '订单明细'));
  fireEvent.click(await screen.findByText('MAT-1 · 10'));
  fireEvent.change(withinDialog(dialog, '数量'), { target: { value: '4' } });
  fireEvent.click(within(dialog).getByRole('button', { name: /确\s*定/ }));
  await waitFor(() => expect(submitted).toMatchObject({
    document_no: 'PR-1', purchase_order_id: orderId, warehouse_id: warehouseId,
    lines: [{ purchase_order_line_id: lineId, item_id: itemId, unit_id: unitId, quantity: 4 }],
  }));
});

it('creates a production receipt from the focused order output', async () => {
  let submitted: Record<string, unknown> | null = null;
  const orderId = '11111111-1111-4111-8111-111111111111';
  const outputId = '22222222-2222-4222-8222-222222222222';
  const itemId = '33333333-3333-4333-8333-333333333333';
  const warehouseId = '55555555-5555-4555-8555-555555555555';
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname === '/api/production/receipts' && init?.method === 'POST') {
      submitted = JSON.parse(String(init.body));
      return new Response(JSON.stringify({ id: 'receipt-1', ...submitted }), { status: 201, headers: { 'Content-Type': 'application/json' } });
    }
    let body: unknown = [];
    if (url.pathname === '/api/system/my-permissions') body = { 'production.receipts': ['view', 'create'] };
    if (url.pathname === '/api/production/orders' && url.search) body = [{ id: orderId, document_no: 'MO-1' }];
    if (url.pathname === `/api/production/orders/${orderId}`) body = { id: orderId, outputs: [
      { id: outputId, item_id: itemId, planned_quantity_base: 6 },
    ] };
    if (url.pathname === '/api/items') body = [{ id: itemId, code: 'FIN-1', name: '成品' }];
    if (url.pathname === '/api/warehouses') body = [{ id: warehouseId, code: 'FINISHED', name: '成品仓' }];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <ResourcePage config={{ ...resources['production.receipts'], initialValues: { production_order_id: orderId },
      listParams: { production_order_id: orderId } }} />
  </QueryClientProvider></AntApp></ConfigProvider>);
  fireEvent.click(await screen.findByRole('button', { name: /新建生产入库/ }));
  const dialog = (await screen.findAllByRole('dialog')).at(-1)!;
  fireEvent.change(withinDialog(dialog, '单号'), { target: { value: 'MAKE-1' } });
  fireEvent.click(screen.getByRole('button', { name: /添加产出入库/ }));
  fireEvent.mouseDown(withinDialog(dialog, '生产订单产出'));
  fireEvent.click(await screen.findByText('FIN-1 · 6'));
  fireEvent.mouseDown(withinDialog(dialog, '目标仓库'));
  fireEvent.click(await screen.findByText('FINISHED · 成品仓'));
  fireEvent.change(withinDialog(dialog, '入库数量'), { target: { value: '6' } });
  fireEvent.click(within(dialog).getByRole('button', { name: /确\s*定/ }));
  await waitFor(() => expect(submitted).toMatchObject({
    document_no: 'MAKE-1', production_order_id: orderId,
    lines: [{ production_order_output_id: outputId, item_id: itemId, target_warehouse_id: warehouseId, quantity_base: 6 }],
  }));
});

it('toggles a user from the list without leaking the password field', async () => {
  let submitted: Record<string, unknown> | null = null;
  const roleId = '22222222-2222-4222-8222-222222222222';
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname === '/api/system/users/user-1' && init?.method === 'PUT') {
      submitted = JSON.parse(String(init.body)) as Record<string, unknown>;
      return new Response(JSON.stringify(submitted), { headers: { 'Content-Type': 'application/json' } });
    }
    const body = url.pathname === '/api/system/my-permissions' ? { 'system.users': ['view', 'update'] }
      : url.pathname === '/api/system/users'
        ? [{ id: 'user-1', username: 'zhangsan', display_name: '张三', department_id: null, role_ids: [roleId], is_active: true }]
        : [];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  setCsrfToken('test-csrf');
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <ResourcePage config={resources['system.users']} />
  </QueryClientProvider></AntApp></ConfigProvider>);
  fireEvent.click(await screen.findByRole('switch', { name: '启用' }));
  // UserUpdate 要求 username/display_name/role_ids，且没有 password 字段。
  await waitFor(() => expect(submitted).toMatchObject({
    username: 'zhangsan', display_name: '张三', department_id: null, role_ids: [roleId], is_active: false,
  }));
  expect(submitted).not.toHaveProperty('password');
});

function withinDialog(dialog: HTMLElement, label: string): HTMLElement {
  const field = dialog.querySelector(`input[id]`);
  const labelled = Array.from(dialog.querySelectorAll('label')).find((node) => node.textContent?.includes(label));
  if (!labelled) throw new Error(`missing label: ${label}`);
  return (dialog.querySelector(`#${labelled.htmlFor}`) ?? field!) as HTMLElement;
}
