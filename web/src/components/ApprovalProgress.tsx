import { Descriptions, Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { get, type Row } from '../api/client';
import { APPROVAL_INSTANCE_STATUS, APPROVAL_TASK_STATUS } from './resource/constants';

/** 单据详情里的审批进度：显示每一级的审批人、状态、时间与意见。 */
export function ApprovalProgress({ documentType, documentId }: {
  documentType: 'sales_order' | 'stocktake'; documentId: string;
}) {
  const instances = useQuery({ queryKey: ['approval-instances', documentType, documentId],
    queryFn: () => get<Row[]>(`/api/approval/documents/${documentType}/${documentId}/instances`), retry: false });
  // 审批人名称来自岗位/用户档案；没有系统管理权限的岗位读不到时退回短 ID。
  const roles = useQuery({ queryKey: ['roles'], queryFn: () => get<Row[]>('/api/system/roles'), retry: false });
  const users = useQuery({ queryKey: ['users'], queryFn: () => get<Row[]>('/api/system/users'), retry: false });
  const rows = instances.data ?? [];
  if (!rows.length) return null;
  const approverOf = (task: Row) => {
    const role = (roles.data ?? []).find((item) => item.id === task.approver_role_id);
    if (role) return `${String(role.code)} · ${String(role.name)}`;
    const user = (users.data ?? []).find((item) => item.id === task.approver_user_id);
    if (user) return `${String(user.username)} · ${String(user.display_name)}`;
    const id = String(task.approver_role_id ?? task.approver_user_id ?? '');
    return id ? `…${id.slice(-8)}` : '—';
  };
  const actedByName = (task: Row) => {
    if (!task.acted_by) return '—';
    const user = (users.data ?? []).find((item) => item.id === task.acted_by);
    return user ? String(user.display_name) : `…${String(task.acted_by).slice(-8)}`;
  };
  return <div>
    <Typography.Title level={5}>审批进度</Typography.Title>
    {rows.map((instance) => <div key={String(instance.id)} className="page-stack">
      <Descriptions bordered size="small" column={3} items={[
        { key: 'status', label: '审批状态', children: <Tag color={instance.status === 'approved' ? 'green' : instance.status === 'rejected' ? 'red' : 'blue'}>
          {APPROVAL_INSTANCE_STATUS[String(instance.status)] ?? String(instance.status)}</Tag> },
        { key: 'submitted', label: '提交时间', children: instance.submitted_at ? dayjs(String(instance.submitted_at)).format('YYYY-MM-DD HH:mm:ss') : '—' },
        { key: 'finished', label: '完成时间', children: instance.finished_at ? dayjs(String(instance.finished_at)).format('YYYY-MM-DD HH:mm:ss') : '—' },
      ]} />
      <Table size="small" rowKey="id" pagination={false} scroll={{ x: 'max-content' }}
        dataSource={instance.tasks as Row[]} columns={[
          { title: '层级', width: 90, render: (_, task) => `第 ${String(task.step_no)} 级` },
          { title: '审批人', render: (_, task) => approverOf(task) },
          { title: '状态', width: 100, render: (_, task) => <Tag color={task.status === 'approved' ? 'green' : task.status === 'rejected' ? 'red' : task.status === 'skipped' ? 'default' : 'blue'}>
            {APPROVAL_TASK_STATUS[String(task.status)] ?? String(task.status)}</Tag> },
          { title: '处理人', width: 130, render: (_, task) => actedByName(task) },
          { title: '处理时间', width: 175, render: (_, task) => task.acted_at ? dayjs(String(task.acted_at)).format('YYYY-MM-DD HH:mm:ss') : '—' },
          { title: '意见', ellipsis: true, render: (_, task) => String(task.opinion ?? '—') },
        ]} />
    </div>)}
  </div>;
}

