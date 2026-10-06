import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import { setCsrfToken } from '../api/client';
import { OrganizationPage } from '../pages/organization/OrganizationPage';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setCsrfToken(''); });

type RenderOptions = {
  permissions?: string[];
  menuPaths?: Record<string, string>;
  putStatus?: number;
  putDetail?: string;
};

function renderPage(options: RenderOptions = {}) {
  const submitted: Record<string, unknown>[] = [];
  let organization = { code: 'FACTORY', name: '注塑科技有限公司', is_active: true };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname === '/api/system/organization' && init?.method === 'PUT') {
      if (options.putStatus) {
        return new Response(JSON.stringify({ detail: options.putDetail ?? '保存失败' }),
          { status: options.putStatus, headers: { 'Content-Type': 'application/json' } });
      }
      expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('test-csrf');
      const body = JSON.parse(String(init.body)) as { name: string };
      submitted.push(body);
      organization = { ...organization, name: body.name };
      return new Response(JSON.stringify(organization), { headers: { 'Content-Type': 'application/json' } });
    }
    const body = url.pathname === '/api/system/organization' ? organization
      : url.pathname === '/api/system/my-permissions' ? { 'system.organization': options.permissions ?? ['view', 'update'] }
      : [];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  setCsrfToken('test-csrf');
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <MemoryRouter><OrganizationPage menuPaths={options.menuPaths ?? {}} /></MemoryRouter>
  </QueryClientProvider></AntApp></ConfigProvider>);
  return { submitted };
}

it('shows the organization identity and profile', async () => {
  renderPage();
  expect(await screen.findByRole('heading', { name: '注塑科技有限公司' })).toBeInTheDocument();
  expect(screen.getAllByText('FACTORY')).toHaveLength(2);
  expect(screen.getByText('组织编码')).toBeInTheDocument();
  expect(screen.getByText('状态')).toBeInTheDocument();
  expect(screen.getByLabelText('组织名称')).toHaveValue('注塑科技有限公司');
});

it('keeps save disabled until the name actually changes', async () => {
  renderPage();
  const save = await screen.findByRole('button', { name: /保\s*存/ });
  expect(save).toBeDisabled();
  fireEvent.change(screen.getByLabelText('组织名称'), { target: { value: '注塑科技有限公司' } });
  expect(save).toBeDisabled();
  fireEvent.change(screen.getByLabelText('组织名称'), { target: { value: '新厂名' } });
  await waitFor(() => expect(save).toBeEnabled());
});

it('submits the trimmed name with CSRF', async () => {
  const { submitted } = renderPage();
  fireEvent.change(await screen.findByLabelText('组织名称'), { target: { value: '  新厂名  ' } });
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }));
  await waitFor(() => expect(submitted).toHaveLength(1));
  expect(submitted[0]).toMatchObject({ name: '新厂名' });
  await waitFor(() => expect(screen.getByLabelText('组织名称')).toHaveValue('新厂名'));
});

it('surfaces the backend message when saving fails', async () => {
  renderPage({ putStatus: 403, putDetail: '没有修改组织的权限' });
  fireEvent.change(await screen.findByLabelText('组织名称'), { target: { value: '新厂名' } });
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }));
  expect(await screen.findByText('没有修改组织的权限')).toBeInTheDocument();
});

it('hides the save controls without update permission', async () => {
  renderPage({ permissions: ['view'] });
  expect(await screen.findByText(/没有修改组织信息的权限/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /保\s*存/ })).not.toBeInTheDocument();
  expect(screen.queryByLabelText('组织名称')).not.toBeInTheDocument();
});

it('only links to system menus the user can reach', async () => {
  renderPage({ menuPaths: { 'system.users': '/system/users' } });
  expect(await screen.findByRole('link', { name: '进入用户' })).toHaveAttribute('href', '/system/users');
  expect(screen.queryByRole('link', { name: '进入角色' })).not.toBeInTheDocument();
});

it('explains when no sibling system menu is reachable', async () => {
  renderPage({ menuPaths: {} });
  expect(await screen.findByText(/暂无其他可访问的系统设置/)).toBeInTheDocument();
});
