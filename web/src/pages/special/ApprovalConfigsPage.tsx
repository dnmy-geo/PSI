import { useState } from 'react';
import { App as AntApp, Button, Card, Select, Space, Switch, Table } from 'antd';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { get, put, type Row } from '../../api/client';

type ApprovalStep = { key: string; kind: 'role' | 'user'; id: string };

export function ApprovalConfigsPage() {
  const { message, modal } = AntApp.useApp();
  const [kind, setKind] = useState<'sales_order' | 'stocktake'>('sales_order');
  // 草稿为 null 表示没改过，直接展示服务端状态；改过之后以草稿为准，
  // 免得后台刷新把正在编辑的内容冲掉。
  const [draft, setDraft] = useState<{ enabled: boolean; steps: ApprovalStep[] } | null>(null);
  const [pending, setPending] = useState(false);
  const configs = useQuery({ queryKey: ['approval-configs'], queryFn: () => get<Row[]>('/api/approval/configs') });
  const roles = useQuery({ queryKey: ['roles'], queryFn: () => get<Row[]>('/api/system/roles') });
  const users = useQuery({ queryKey: ['users'], queryFn: () => get<Row[]>('/api/system/users') });
  const current = configs.data?.find((row) => row.document_type === kind);
  const server = {
    enabled: Boolean(current?.is_enabled ?? true),
    steps: ((current?.steps ?? []) as Row[]).map((step) => ({
      key: String(step.id), kind: step.approver_role_id ? 'role' as const : 'user' as const,
      id: String(step.approver_role_id ?? step.approver_user_id ?? ''),
    })),
  };
  const value = draft ?? server;
  const edit = (next: { enabled?: boolean; steps?: ApprovalStep[] }) =>
    setDraft({ enabled: value.enabled, steps: value.steps, ...next });
  const switchKind = (next: 'sales_order' | 'stocktake') => {
    if (next === kind) return;
    if (!draft) { setKind(next); return; }
    modal.confirm({ title: '放弃未保存的修改？', content: '切换单据类型会丢失当前改动。',
      okText: '放弃并切换', okButtonProps: { danger: true }, cancelText: '继续编辑',
      onOk: () => { setKind(next); setDraft(null); } });
  };
  const save = async () => {
    if (!value.steps.length) { message.warning('至少需要一级审批'); return; }
    if (value.steps.some((step) => !step.id)) { message.warning('请为每一级选择审批人或岗位'); return; }
    setPending(true);
    try {
      await put(`/api/approval/configs/${kind}`, {
        is_enabled: value.enabled,
        steps: value.steps.map((step) => step.kind === 'role'
          ? { approver_role_id: step.id } : { approver_user_id: step.id }),
      });
      await configs.refetch();
      setDraft(null);
      message.success('审批配置已保存');
    } catch (error) { message.error((error as Error).message); } finally { setPending(false); }
  };
  const approverOptions = (step: ApprovalStep) => step.kind === 'role'
    ? (roles.data ?? []).map((role) => ({ value: String(role.id), label: `${String(role.code)} · ${String(role.name)}` }))
    : (users.data ?? []).map((user) => ({ value: String(user.id), label: `${String(user.username)} · ${String(user.display_name)}` }));
  return <PageContainer title="审批配置" extra={<Space>
    <Select style={{ width: 160 }} value={kind} onChange={switchKind}
      options={[{ value: 'sales_order', label: '销售订单' }, { value: 'stocktake', label: '库存盘点' }]} />
    <Button disabled={value.steps.length >= 5}
      onClick={() => edit({ steps: [...value.steps, { key: `new-${Date.now()}`, kind: 'role', id: '' }] })}>添加审批层级</Button>
    <Button type="primary" loading={pending} disabled={!draft} onClick={save}>保存</Button>
  </Space>}>
    <Card extra={<Space size={8}>
      <span className="dim">启用审批</span>
      <Switch checked={value.enabled} onChange={(enabled) => edit({ enabled })} />
    </Space>}>
      <p className="approval-hint">按顺序审批，逐级通过后单据才生效。表格里直接修改，改完点右上角「保存」。</p>
      <Table<ApprovalStep> rowKey="key" dataSource={value.steps} pagination={false}
        loading={configs.isPending || (roles.isPending && !roles.data) || (users.isPending && !users.data)}
        locale={{ emptyText: '还没有审批层级，点右上角「添加审批层级」' }}
        columns={[
          { title: '层级', width: 100, render: (_, __, index) => `第 ${index + 1} 级` },
          { title: '审批方式', width: 130, render: (_, step) => <Select style={{ width: '100%' }} value={step.kind}
            options={[{ value: 'role', label: '按岗位' }, { value: 'user', label: '按用户' }]}
            // 换类型时清掉已选的人，否则会把岗位 id 当成用户 id 提交。
            onChange={(next) => edit({ steps: value.steps.map((item) => item.key === step.key
              ? { ...item, kind: next as 'role' | 'user', id: '' } : item) })} /> },
          { title: '审批人', render: (_, step) => <Select style={{ width: '100%' }} showSearch optionFilterProp="label"
            placeholder={step.kind === 'role' ? '选择审批岗位' : '选择审批人'} value={step.id || undefined}
            options={approverOptions(step)} status={step.id ? undefined : 'warning'}
            onChange={(next) => edit({ steps: value.steps.map((item) => item.key === step.key
              ? { ...item, id: String(next) } : item) })} /> },
          { title: '操作', width: 90, fixed: 'right', render: (_, step) => [
            <Button key="del" type="link" danger size="small"
              onClick={() => edit({ steps: value.steps.filter((item) => item.key !== step.key) })}>删除</Button>,
          ] },
        ]} />
    </Card>
  </PageContainer>;
}

// 后端写入的 action_code 形如 "sales_shipment.post"，按「对象 · 动作」拆开翻译；未登记的值原样显示。
