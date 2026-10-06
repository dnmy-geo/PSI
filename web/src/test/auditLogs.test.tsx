import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import { AuditLogsPage } from '../pages/special';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// 接口返回的是 occurred_at / actor_name；曾经这里按 created_at / actor_id 取值，导致时间列整列为空。
const rows = [{
  id: 'log-1', actor_id: 'c4950461-3e24-44e1-b180-1b75573ea5de', actor_name: '系统管理员',
  action_code: 'sales_shipment.post', document_type: 'sales_shipment',
  document_id: '11111111-1111-4111-8111-111111111111', document_label: 'DEMO-SD-004', reason: null,
  change_summary: null, occurred_at: '2026-10-03T15:54:41.123372+08:00',
}, {
  // 单据已删除时后端给不出单号，前端回退显示截断的 UUID。
  id: 'log-2', actor_id: 'c4950461-3e24-44e1-b180-1b75573ea5de', actor_name: '系统管理员',
  action_code: 'role.create', document_type: 'role',
  document_id: 'cd403497-a8ea-4858-a1b6-603aa5360f1b', document_label: null, reason: null,
  change_summary: null, occurred_at: '2026-10-03T15:41:06.123372+08:00',
}];

function renderPage() {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    return new Response(JSON.stringify(url.pathname === '/api/system/audit-logs' ? rows : []),
      { headers: { 'Content-Type': 'application/json' } });
  }));
  render(<ConfigProvider><AntApp><QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuditLogsPage />
  </QueryClientProvider></AntApp></ConfigProvider>);
}

it('shows the audit time from occurred_at in a readable form', async () => {
  renderPage();
  const cells = await screen.findAllByText(/^2026-10-03 \d{2}:\d{2}:\d{2}$/);
  // 两行都有时间，说明没有一列取不到 occurred_at 而退化成“—”。时区不同也只影响小时位。
  expect(cells).toHaveLength(2);
  expect(cells[0].textContent).toMatch(/^2026-10-03 \d{2}:54:41$/);
});

it('translates the action code and prefers the actor name over the id', async () => {
  renderPage();
  expect(await screen.findByText('销售出库 · 过账')).toBeInTheDocument();
  expect(screen.getAllByText('系统管理员')).not.toHaveLength(0);
  expect(screen.queryByText('c4950461-3e24-44e1-b180-1b75573ea5de')).not.toBeInTheDocument();
});

it('shows the document number, falling back to a shortened id when there is none', async () => {
  renderPage();
  expect(await screen.findByText('DEMO-SD-004')).toBeInTheDocument();
  expect(screen.queryByText('11111111-1111-4111-8111-111111111111')).not.toBeInTheDocument();
  // 单据已删除时只剩截断的 UUID，完整值放在悬浮提示里
  expect(screen.getByText('cd403497…')).toBeInTheDocument();
});
