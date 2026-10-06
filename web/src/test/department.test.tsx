import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import { setCsrfToken } from '../api/client';
import { resources } from '../configs';
import { ResourcePage } from '../components/resource';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setCsrfToken(''); });

it('creates a department without entering a code', async () => {
  let submitted: Record<string, unknown> | null = null;
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === '/api/system/departments' && init?.method === 'POST') {
      submitted = JSON.parse(String(init.body));
      return new Response(JSON.stringify({ id: 'department-1', code: 'DEP-0001', ...submitted }),
        { status: 201, headers: { 'Content-Type': 'application/json' } });
    }
    const body = path === '/api/system/my-permissions'
      ? { 'system.departments': ['view', 'create', 'update', 'delete'] } : [];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <ResourcePage config={resources['system.departments']} />
  </QueryClientProvider></AntApp></ConfigProvider>);
  fireEvent.click(await screen.findByRole('button', { name: /新建部门/ }));
  const dialog = await screen.findByRole('dialog', { name: '新建部门' });
  const codeLabel = within(dialog).getByText('部门编码', { selector: 'label' }) as HTMLLabelElement;
  expect(dialog.querySelector(`#${codeLabel.htmlFor}`)).toHaveAttribute('placeholder', '留空自动生成，如 DEP-0001');
  fireEvent.change(within(dialog).getByLabelText('部门名称'), { target: { value: '生产部' } });
  fireEvent.click(within(dialog).getByRole('button', { name: /确\s*定/ }));
  await waitFor(() => expect(submitted).toMatchObject({ name: '生产部' }));
  expect(submitted).not.toHaveProperty('code');
});

const existingDepartment = { id: 'department-1', code: 'DEP-0001', name: '生产部', parent_id: null, is_active: true };

function stubDepartmentFetch(extra?: (path: string, init: RequestInit | undefined) => Response | null) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const handled = extra?.(path, init);
    if (handled) return handled;
    const body = path === '/api/system/my-permissions'
      ? { 'system.departments': ['view', 'create', 'update', 'delete'] }
      : path === '/api/system/departments' ? [existingDepartment] : [];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  setCsrfToken('test-csrf');
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <ResourcePage config={resources['system.departments']} />
  </QueryClientProvider></AntApp></ConfigProvider>);
}

it('lays out the department form in a single column', async () => {
  stubDepartmentFetch();
  fireEvent.click(await screen.findByRole('button', { name: /新建部门/ }));
  const dialog = await screen.findByRole('dialog', { name: '新建部门' });
  expect(dialog.querySelector('.psi-editor-fields')).toHaveClass('is-single-column');
});

it('toggles 启用 straight from the list without opening the editor', async () => {
  let submitted: Record<string, unknown> | null = null;
  let csrf: string | null = null;
  stubDepartmentFetch((path, init) => {
    if (path !== '/api/system/departments/department-1' || init?.method !== 'PUT') return null;
    csrf = new Headers(init.headers).get('X-CSRF-Token');
    submitted = JSON.parse(String(init.body)) as Record<string, unknown>;
    return new Response(JSON.stringify({ ...existingDepartment, ...submitted }), { headers: { 'Content-Type': 'application/json' } });
  });
  const toggle = await screen.findByRole('switch', { name: '启用' });
  expect(toggle).toBeChecked();
  fireEvent.click(toggle);
  // DepartmentWrite 的 code/name 必填，开关必须带上该行其余字段，否则后端 422。
  await waitFor(() => expect(submitted).toMatchObject({
    code: 'DEP-0001', name: '生产部', parent_id: null, is_active: false,
  }));
  expect(csrf).toBe('test-csrf');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
