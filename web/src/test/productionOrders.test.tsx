import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ProductionDocumentPage, ProductionOrdersPage } from '../pages/special';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('opens receipt records for the selected production order', async () => {
  const orderId = '11111111-1111-4111-8111-111111111111';
  const receiptQueries: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    let body: unknown = [];
    if (url.pathname === '/api/system/my-permissions') body = {
      'production.orders': ['view'], 'production.receipts': ['view', 'create'],
    };
    if (url.pathname === '/api/production/orders' && url.searchParams.has('limit')) {
      body = [{ id: orderId, document_no: 'MO-1', document_date: '2026-10-01', status: 'open' }];
    }
    if (url.pathname === `/api/production/orders/${orderId}`) body = { id: orderId, document_no: 'MO-1', status: 'open', outputs: [] };
    if (url.pathname === '/api/production/receipts') receiptQueries.push(url.search);
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <MemoryRouter initialEntries={['/production/orders']}><Routes>
      <Route path="/production/orders" element={<ProductionOrdersPage />} />
      <Route path="/production/receipts" element={<ProductionDocumentPage kind="receipts" />} />
    </Routes></MemoryRouter>
  </QueryClientProvider></AntApp></ConfigProvider>);
  expect(await screen.findByText('MO-1')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '入库' }));
  expect(await screen.findByText('当前生产订单：MO-1')).toBeInTheDocument();
  await waitFor(() => expect(receiptQueries.some((query) =>
    new URLSearchParams(query).get('production_order_id') === orderId)).toBe(true));
});
