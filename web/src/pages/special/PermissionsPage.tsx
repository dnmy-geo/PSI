import { useState } from 'react';
import { App as AntApp, Button, Checkbox, Select, Space, Table } from 'antd';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { get, put, type Row } from '../../api/client';
import { ListFilterBar, type FilterValues } from '../../components/ListFilterBar';
import { matchesKeyword } from '../../utils/listFilters';

const actionLabels: Record<string, string> = {
  view: '查看', create: '新增', update: '修改', delete: '删除', submit: '提交',
  post: '生效 / 过账', approve: '审批', reverse: '冲销', adjust: '库存调整', force_close: '强制结束',
};

export function PermissionsPage() {
  const { message, modal } = AntApp.useApp();
  const roles = useQuery({ queryKey: ['roles'], queryFn: () => get<Row[]>('/api/system/roles') });
  const menus = useQuery({ queryKey: ['all-menus'], queryFn: () => get<Row[]>('/api/system/menus') });
  const [roleId, setRoleId] = useState('');
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [dirty, setDirty] = useState(false);
  const [savePending, setSavePending] = useState(false);
  const [filters, setFilters] = useState<FilterValues>({});
  const permissions = useQuery({ queryKey: ['role-permissions', roleId], enabled: !!roleId,
    queryFn: () => get<{ menu_id: string; action_code: string }[]>(`/api/system/roles/${roleId}/permissions`) });
  const values: Record<string, string[]> = dirty ? selected : Object.fromEntries((menus.data ?? []).map((menu) => [menu.id,
    (permissions.data ?? []).filter((permission) => permission.menu_id === menu.id).map((permission) => permission.action_code)]));
  // 管理员专属菜单由 require_admin 把关，授给普通岗位只会产生点开即 403 的死菜单，因此不出现在可勾选范围。
  const delegatable = (menus.data ?? []).filter((menu) => !menu.admin_only);
  const switchRole = (next: string) => {
    if (!next) return;
    if (!dirty) { setRoleId(next); return; }
    modal.confirm({ title: '放弃未保存的权限修改？', content: '切换岗位会丢失当前未保存的改动。',
      okText: '放弃并切换', okButtonProps: { danger: true }, cancelText: '继续编辑',
      onOk: () => { setRoleId(next); setSelected({}); setDirty(false); } });
  };
  const actionOptions = Object.entries(actionLabels).map(([value, label]) => ({ value, label }));
  // 后端要求非查看动作必须伴随查看。取消查看时整行清空——留下「有修改无查看」的组合会被后端 422 拒绝。
  const toggleActions = (menu: Row, next: string[]) => {
    const current = values[String(menu.id)] ?? [];
    const hasView = next.includes('view');
    const resolved = current.includes('view') && !hasView ? []
      : !hasView && next.length > 0 ? ['view', ...next] : next;
    setSelected({ ...values, [String(menu.id)]: resolved });
    setDirty(true);
  };
  // 批量操作只改暂存值，仍要点「保存权限」才写库——避免误点直接生效。
  const stage = (next: Record<string, string[]>) => { setSelected({ ...values, ...next }); setDirty(true); };
  const rows = delegatable.filter((menu) => menu.parent_id && matchesKeyword(menu, filters.keyword ?? '', ['code', 'name']));
  const applyAll = (actions: string[], label: string) => {
    modal.confirm({ title: `${label}（${rows.length} 个菜单）`,
      content: '改动先暂存，点「保存权限」后才写入。',
      okText: label, okButtonProps: { danger: actions.length === 0 },
      onOk: () => stage(Object.fromEntries(rows.map((menu) => [String(menu.id), actions]))) });
  };
  const copyFrom = async (sourceId: string) => {
    if (!sourceId) return;
    try {
      const source = await get<{ menu_id: string; action_code: string }[]>(`/api/system/roles/${sourceId}/permissions`);
      const allowed = new Set(delegatable.map((menu) => String(menu.id)));
      const next: Record<string, string[]> = Object.fromEntries(delegatable.map((menu) => [String(menu.id), []]));
      // 只搬运可委派菜单：来源岗位若残留管理员专属菜单的授权，照搬会在保存时被后端拒绝。
      for (const permission of source) if (allowed.has(permission.menu_id)) next[permission.menu_id].push(permission.action_code);
      stage(next);
      message.success('已套用该岗位的权限，检查后点「保存权限」');
    } catch (error) { message.error((error as Error).message); }
  };
  return <PageContainer title="岗位权限配置" extra={<Space>
    <Select style={{ width: 240 }} placeholder="选择岗位角色" value={roleId || undefined} onChange={switchRole}
      options={(roles.data ?? []).filter((role) => role.code !== 'system_admin').map((role) => ({ value: role.id as string, label: `${role.code} · ${role.name}` }))} />
    <Select style={{ width: 200 }} placeholder="复制自其他岗位" value={undefined} disabled={!roleId} onChange={copyFrom}
      options={(roles.data ?? []).filter((role) => role.code !== 'system_admin' && role.id !== roleId)
        .map((role) => ({ value: role.id as string, label: `${role.code} · ${role.name}` }))} />
    <Button type="primary" loading={savePending} disabled={!roleId || !dirty} onClick={async () => {
      const pairs = Object.entries(values).flatMap(([menu_id, actions]) => actions.map((action_code) => ({ menu_id, action_code })));
      setSavePending(true);
      try {
        await put(`/api/system/roles/${roleId}/permissions`, { permissions: pairs });
        // 必须等新数据回来再清 dirty：否则 values 会从旧的 permissions.data 重算，界面闪回旧值。
        await permissions.refetch();
        setDirty(false);
        message.success('权限已保存');
      } catch (error) {
        message.error((error as Error).message);
      } finally { setSavePending(false); }
    }}>保存权限</Button>
  </Space>}>
    <ListFilterBar fields={[{ key: 'keyword', label: '菜单编码或名称' }]} onApply={setFilters} />
    <div className="perm-bar">
      <p className="perm-hint">点击标签直接勾选。勾选「查看」以外的动作会自动带上「查看」；取消「查看」会清空该菜单。</p>
      <Space size={6}>
        <Button size="small" disabled={!roleId || !rows.length} onClick={() => applyAll(['view'], '全部只读')}>全部只读</Button>
        <Button size="small" disabled={!roleId || !rows.length} onClick={() => applyAll(['view', 'create', 'update'], '全部可录入')}>全部可录入</Button>
        <Button size="small" danger disabled={!roleId || !rows.length} onClick={() => applyAll([], '全部清空')}>全部清空</Button>
      </Space>
    </div>
    <Table rowKey="id" dataSource={rows} loading={menus.isPending || permissions.isPending && !!roleId}
      pagination={{ pageSize: 15 }} columns={[{ title: '菜单', width: 260, render: (_, menu) => `${menu.code} · ${menu.name}` },
        { title: '岗位操作权限', render: (_, menu) => <div className="perm-cell">
          <Checkbox.Group className="perm-actions" disabled={!roleId} value={values[String(menu.id)] ?? []}
            options={actionOptions} onChange={(next) => toggleActions(menu, next as string[])} />
          <span className="perm-quick">
            <Button type="link" size="small" disabled={!roleId} onClick={() => stage({ [String(menu.id)]: ['view'] })}>只读</Button>
            <Button type="link" size="small" disabled={!roleId} onClick={() => stage({ [String(menu.id)]: ['view', 'create', 'update'] })}>录入</Button>
            <Button type="link" size="small" danger disabled={!roleId} onClick={() => stage({ [String(menu.id)]: [] })}>清空</Button>
          </span>
        </div> },
      ]} />
  </PageContainer>;
}

