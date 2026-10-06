import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import { setCsrfToken } from '../api/client';
import { PermissionsPage } from '../pages/special';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setCsrfToken(''); });

const clerk = { id: 'role-clerk', code: 'clerk', name: '业务员', is_active: true };
const buyer = { id: 'role-buyer', code: 'buyer', name: '采购员', is_active: true };
const menus = [
  { id: 'menu-system', code: 'system', name: '系统管理', parent_id: null, admin_only: false },
  { id: 'menu-users', code: 'system.users', name: '用户', parent_id: 'menu-system', admin_only: true },
  { id: 'menu-inventory', code: 'inventory', name: '库存', parent_id: null, admin_only: false },
  { id: 'menu-query', code: 'inventory.query', name: '库存查询', parent_id: 'menu-inventory', admin_only: false },
];

function renderPage() {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    const body = url.pathname === '/api/system/roles' ? [clerk, buyer]
      : url.pathname === '/api/system/menus' ? menus
      : url.pathname.startsWith('/api/system/roles/') ? []
      : [];
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  }));
  setCsrfToken('test-csrf');
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ConfigProvider><AntApp><QueryClientProvider client={queryClient}>
    <PermissionsPage />
  </QueryClientProvider></AntApp></ConfigProvider>);
}

it('only offers menus that a role can actually be granted', async () => {
  renderPage();
  expect(await screen.findByText('inventory.query · 库存查询')).toBeInTheDocument();
  // system.users 由 require_admin 把关，授给岗位只会得到点开即 403 的死菜单
  expect(screen.queryByText('system.users · 用户')).not.toBeInTheDocument();
});

// antd 的 Select 关闭后选项仍留在 DOM 里，必须只在展开的下拉中点击，否则会点到隐藏节点。
// 多选下拉要触发 .ant-select-selector；下拉容器先于选项渲染，且页面上可能同时存在多个
// 下拉容器，所以在所有展开的下拉里找目标选项。
async function pickOption(combobox: HTMLElement, title: string) {
  fireEvent.mouseDown(combobox.closest('.ant-select')?.querySelector('.ant-select-selector') ?? combobox);
  const option = await waitFor(() => {
    const open = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')];
    for (const dropdown of open) {
      const found = within(dropdown as HTMLElement).queryByTitle(title);
      if (found) return found;
    }
    throw new Error(`option not rendered yet: ${title}`);
  });
  fireEvent.click(option);
}

it('keeps 查看 granted with any other action, and clears the row when 查看 is removed', async () => {
  renderPage();
  await screen.findByText('inventory.query · 库存查询');
  const [roleSelect] = screen.getAllByRole('combobox');
  await pickOption(roleSelect, 'clerk · 业务员');
  const row = (await screen.findByText('inventory.query · 库存查询')).closest('tr')!;
  const box = (name: string) => within(row).getByRole('checkbox', { name });

  fireEvent.click(box('新增'));
  await waitFor(() => expect(box('查看')).toBeChecked());   // 后端要求非查看动作必须伴随查看

  fireEvent.click(box('查看'));                              // 取消查看即整行清空
  await waitFor(() => expect(box('新增')).not.toBeChecked());
  expect(box('查看')).not.toBeChecked();
});

it('applies a whole row preset in one click', async () => {
  renderPage();
  await screen.findByText('inventory.query · 库存查询');
  const [roleSelect] = screen.getAllByRole('combobox');
  await pickOption(roleSelect, 'clerk · 业务员');
  const row = (await screen.findByText('inventory.query · 库存查询')).closest('tr')!;

  fireEvent.click(within(row).getByRole('button', { name: '录入' }));
  await waitFor(() => expect(within(row).getByRole('checkbox', { name: '查看' })).toBeChecked());
  expect(within(row).getByRole('checkbox', { name: '新增' })).toBeChecked();
  expect(within(row).getByRole('checkbox', { name: '修改' })).toBeChecked();
  expect(within(row).getByRole('checkbox', { name: '删除' })).not.toBeChecked();

  fireEvent.click(within(row).getByRole('button', { name: '清空' }));
  await waitFor(() => expect(within(row).getByRole('checkbox', { name: '查看' })).not.toBeChecked());
});

it('clears every filtered row only after the confirmation is accepted', async () => {
  renderPage();
  await screen.findByText('inventory.query · 库存查询');
  const [roleSelect] = screen.getAllByRole('combobox');
  await pickOption(roleSelect, 'clerk · 业务员');
  const row = (await screen.findByText('inventory.query · 库存查询')).closest('tr')!;
  fireEvent.click(within(row).getByRole('button', { name: '录入' }));
  await waitFor(() => expect(within(row).getByRole('checkbox', { name: '查看' })).toBeChecked());

  fireEvent.click(screen.getByRole('button', { name: '全部清空' }));
  const dialog = await screen.findByRole('dialog');
  // 弹窗写明影响范围；antd 会把标题额外渲染一份给读屏，故按元素精确断言。
  expect(dialog.querySelector('.ant-modal-confirm-title')?.textContent).toBe('全部清空（1 个菜单）');
  fireEvent.click(within(dialog).getByRole('button', { name: '全部清空' }));
  await waitFor(() => expect(within(row).getByRole('checkbox', { name: '查看' })).not.toBeChecked());
});

it('asks before discarding unsaved grants when switching role', async () => {
  renderPage();
  await screen.findByText('inventory.query · 库存查询');   // 等岗位与菜单两个查询都落地再操作
  const [roleSelect] = screen.getAllByRole('combobox');
  await pickOption(roleSelect, 'clerk · 业务员');

  // 勾一个动作，制造未保存状态（动作现在是平铺的标签，直接点击）
  const row = (await screen.findByText('inventory.query · 库存查询')).closest('tr')!;
  fireEvent.click(within(row).getByRole('checkbox', { name: '查看' }));
  await waitFor(() => expect(screen.getByRole('button', { name: /保存权限/ })).toBeEnabled());

  // 此时切换岗位必须确认，而不是静默丢弃
  await pickOption(roleSelect, 'buyer · 采购员');
  await waitFor(() => expect(document.querySelector('.ant-modal-confirm')).not.toBeNull());
  expect(document.body.textContent).toContain('放弃未保存的权限修改');
  // 未确认前岗位不能变，改动也不能丢
  expect(document.querySelector('.ant-select-selection-item')?.textContent).toBe('clerk · 业务员');
  fireEvent.click(screen.getByRole('button', { name: '继续编辑' }));
  await waitFor(() => expect(screen.getByRole('button', { name: /保存权限/ })).toBeEnabled());
  expect(document.querySelector('.ant-select-selection-item')?.textContent).toBe('clerk · 业务员');
});
