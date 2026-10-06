import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import { InitializationPage } from '../pages/special';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('provides opening balance, unfinished-business imports and historical return source', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    const body = path === '/api/system/carryover/documents?kind=sales'
      ? [{ id: 'carry-1', original_document_no: 'OLD-SO', document_no: 'NEW-SO', line_count: 1 }]
      : path === '/api/system/carryover/documents/carry-1'
        ? { original_document_no: 'OLD-SO', document_no: 'NEW-SO', effective_date: '2026-10-01',
            lines: [{ source_row_no: 2, item_code: 'FIN', original_quantity_base: '10',
              completed_quantity_base: '4', remaining_quantity_base: '6',
              historical_source_no: 'HIST-SH-OLD-SO', historical_source_id: 'source-1' }] }
        : [];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <MemoryRouter><InitializationPage /></MemoryRouter>
  </QueryClientProvider></AntApp></ConfigProvider>);
  expect(screen.getByRole('button', { name: '预览并校验' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '导入草稿' })).toBeDisabled();
  fireEvent.click(screen.getByRole('tab', { name: '期初往来余额' }));
  expect(await screen.findByRole('link', { name: '下载模板' })).toHaveAttribute(
    'href', '/api/reconciliation/opening-balances/template');
  expect(screen.getByRole('button', { name: '预览并校验' })).toBeDisabled();
  fireEvent.click(screen.getByRole('tab', { name: '未完成业务接续' }));
  for (const [tab, kind] of [
    ['销售未发', 'sales'], ['采购未入', 'purchase'],
    ['生产未完', 'production'], ['委外未完', 'outsourcing'],
  ]) {
    fireEvent.click(screen.getByRole('tab', { name: tab }));
    const active = screen.getByRole('tabpanel', { name: tab });
    expect(within(active).getByRole('link', { name: '下载模板' })).toHaveAttribute(
      'href', `/api/system/carryover/template/${kind}`);
    expect(within(active).getByRole('button', { name: '确认导入草稿' })).toBeDisabled();
    if (kind === 'sales') {
      fireEvent.click(await within(active).findByRole('button', { name: '查看明细' }));
      expect(await screen.findByText('HIST-SH-OLD-SO')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '以此来源办理退货' })).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    }
  }
}, 20_000);
