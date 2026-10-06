import { useState } from 'react';
import { Alert, App as AntApp, Button, Descriptions, Input, Modal, Table, Tabs, Tag, Tooltip, Typography } from 'antd';
import { ArrowRightOutlined, CheckCircleOutlined, ClockCircleOutlined, ExperimentOutlined, InboxOutlined, ShopOutlined, ShoppingCartOutlined, ToolOutlined } from '@ant-design/icons';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { get, getPage, post, type Row } from '../../api/client';
import { ListFilterBar, type FilterValues } from '../../components/ListFilterBar';
import { getAllPages, matchesKeyword } from '../../utils/listFilters';
import { ApprovalProgress } from '../../components/ApprovalProgress';
import { APPROVAL_TASK_STATUS, FIELD_LABELS, HIDDEN_DETAIL_FIELDS } from '../../components/resource';

const overviewMetrics = [
  { key: 'approved_sales_orders', label: '已审批销售订单', detail: '销售', icon: <ShopOutlined />, tone: 'blue' },
  { key: 'open_purchase_orders', label: '进行中的采购订单', detail: '采购', icon: <ShoppingCartOutlined />, tone: 'cyan' },
  { key: 'open_production_plans', label: '进行中的生产计划', detail: '计划', icon: <ExperimentOutlined />, tone: 'violet' },
  { key: 'open_production_orders', label: '进行中的生产订单', detail: '生产', icon: <ToolOutlined />, tone: 'orange' },
  { key: 'open_outsourcing_orders', label: '进行中的委外单', detail: '委外', icon: <ArrowRightOutlined />, tone: 'slate' },
  { key: 'counting_stocktakes', label: '清点中的盘点单', detail: '库存', icon: <InboxOutlined />, tone: 'green' },
] as const;

export type WorkbenchAccess = { overview: boolean; tasks: boolean; alerts: boolean };

function Overview({ onOpenTasks }: { onOpenTasks?: () => void }) {
  const query = useQuery({ queryKey: ['overview'], queryFn: () => get<Record<string, number>>('/api/workbench/overview') });
  const metricValue = (key: string) => query.isPending || query.isError ? '—' : (query.data?.[key] ?? 0).toLocaleString('zh-CN');
  const date = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' }).format(new Date());
  return <div className="overview-shell">
      <section className="overview-hero" aria-label="工作台概览">
        <div className="overview-hero-copy">
          <div className="overview-eyebrow"><span className="overview-live-dot" /> 工作台 · {date}</div>
          <h2>让每一步业务，<br />都清晰可见。</h2>
          <p>从待审批事项到销售、采购与生产进度，在这里掌握今天的业务状态。</p>
          {onOpenTasks && <button className="overview-hero-link" type="button" onClick={onOpenTasks}>查看我的待办 <ArrowRightOutlined /></button>}
        </div>
        <div className="overview-hero-focus">
          <div className="overview-focus-icon"><ClockCircleOutlined /></div>
          <span className="overview-focus-label">我的待审批</span>
          <strong>{metricValue('pending_my_approvals')}</strong>
          <span className="overview-focus-note">项业务等待处理</span>
          <span className="overview-focus-bottom"><CheckCircleOutlined /> 从这里开始今天的工作</span>
        </div>
      </section>
      {query.isError && <div className="overview-error" role="alert">业务数据暂时无法读取，请刷新重试。</div>}
      <div className="overview-section-heading">
        <div><span className="overview-section-kicker">OPERATIONS</span><h3>业务运行情况</h3></div>
        <Button size="small" onClick={() => query.refetch()}>刷新数据</Button>
      </div>
      <div className="overview-metrics">
        {overviewMetrics.map((metric) => <article className={`overview-metric overview-metric-${metric.tone}`} key={metric.key}>
          <div className="overview-metric-top"><span className="overview-metric-icon">{metric.icon}</span><span className="overview-metric-detail">{metric.detail}</span></div>
          <div className="overview-metric-main"><strong>{metricValue(metric.key)}</strong><span>{metric.label}</span></div>
          <div className="overview-metric-rule" />
        </article>)}
      </div>
  </div>;
}

const TASK_DOCUMENT_TYPES: Record<string, string> = { sales_order: '销售订单', stocktake: '库存盘点' };
const TASK_DOCUMENT_PATHS: Record<string, string> = { sales_order: '/api/sales/orders', stocktake: '/api/inventory/stocktakes' };

function Tasks() {
  const { message, modal } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [version, setVersion] = useState(0);
  const [detail, setDetail] = useState<Row | null>(null);
  const [detailType, setDetailType] = useState('');
  const [filters, setFilters] = useState<FilterValues>({});
  // 待办里显示单号而不是 UUID；没有该单据查看权限时退回短 ID。
  const documents = useQuery({ queryKey: ['task-documents'], retry: false, queryFn: async () => {
    const result: Record<string, string> = {};
    for (const [type, path] of Object.entries(TASK_DOCUMENT_PATHS)) {
      try { for (const row of await getAllPages(path)) result[`${type}:${String(row.id)}`] = String(row.document_no); }
      catch { /* 无权限，保持短 ID */ }
    }
    return result;
  } });
  const documentLabel = (row: Row) => documents.data?.[`${String(row.document_type)}:${String(row.document_id)}`]
    ?? (row.document_id ? `…${String(row.document_id).slice(-8)}` : '—');
  const openDocument = async (row: Row) => {
    const kind = String(row.document_type);
    const endpoint = kind === 'sales_order' ? '/api/sales/orders' : kind === 'stocktake' ? '/api/inventory/stocktakes' : '';
    if (!endpoint) { message.error('不支持的审批单据类型'); return; }
    try { setDetail(await get<Row>(`${endpoint}/${row.document_id}`)); setDetailType(kind); }
    catch (error) { message.error((error as Error).message); }
  };
  // 与单据动作一致：被拒绝时带着错误重开确认框，不在 onOk 里抛出（antd 会留下未处理的 promise 拒绝）。
  const decide = (row: Row, decision: 'approve' | 'reject', initial = '', failure?: string) => {
    let opinion = initial;
    modal.confirm({ title: decision === 'approve' ? '同意审批' : '驳回审批',
      content: <div className="page-stack">
        {failure && <Alert type="error" showIcon message={failure} />}
        <Input.TextArea defaultValue={initial} placeholder="审批意见；驳回时必填"
          onChange={(event) => { opinion = event.target.value; }} />
      </div>,
      okText: decision === 'approve' ? '同意' : '驳回', okButtonProps: { danger: decision === 'reject' },
      onOk: async () => {
        if (decision === 'reject' && !opinion.trim()) {
          message.warning('请填写驳回意见');
          decide(row, decision, opinion, '请填写驳回意见');
          return;
        }
        try {
          await post(`/api/approval/tasks/${row.id}/decision`, { decision, opinion: opinion.trim() || null });
          message.success('审批完成'); setVersion((value) => value + 1);
          // 顺手把侧边栏「工作台」的待审批角标也刷新掉，不用等下一次轮询。
          queryClient.invalidateQueries({ queryKey: ['my-pending-approvals'] });
        }
        catch (error) { const text = (error as Error).message; message.error(text); decide(row, decision, opinion, text); }
      },
    });
  };
  return <div className="workbench-tab-panel"><ListFilterBar fields={[{ key: 'keyword', label: '单据类型或单号' }, { key: 'status', label: '状态' }]} onApply={setFilters} />
    <ProTable<Row> key={`${version}-${JSON.stringify(filters)}`} rowKey="id" search={false} pagination={{ pageSize: 10 }}
    headerTitle="我的待办事项"
    request={async (params) => { const page = params.current ?? 1; const size = params.pageSize ?? 10;
      if (Object.values(filters).some(Boolean)) {
        const rows = (await getAllPages('/api/approval/tasks/mine')).filter((row) =>
          matchesKeyword({ ...row, type_label: TASK_DOCUMENT_TYPES[String(row.document_type)] ?? '',
            document_label: documentLabel(row) }, filters.keyword ?? '',
            ['type_label', 'document_label', 'document_type', 'document_id', 'step_no']) &&
          (!filters.status || String(row.status ?? '').toLocaleLowerCase().includes(filters.status.trim().toLocaleLowerCase())));
        return { data: rows.slice((page - 1) * size, page * size), success: true, total: rows.length };
      }
      const { data, total } = await getPage<Row[]>('/api/approval/tasks/mine', { limit: size, offset: (page - 1) * size });
      return { data, success: true, total };
    }}
    columns={[
      { title: '单据类型', dataIndex: 'document_type', width: 120,
        render: (_, row) => TASK_DOCUMENT_TYPES[String(row.document_type)] ?? String(row.document_type ?? '—') },
      { title: '单据', dataIndex: 'document_id', ellipsis: true,
        render: (_, row) => <Tooltip title={String(row.document_id ?? '')}>
          <span className={documents.data?.[`${String(row.document_type)}:${String(row.document_id)}`] ? undefined : 'mono dim'}>
            {documentLabel(row)}
          </span>
        </Tooltip> },
      { title: '审批步骤', dataIndex: 'step_no', width: 110, render: (_, row) => `第 ${String(row.step_no)} 级` },
      { title: '状态', dataIndex: 'status', width: 100,
        render: (_, row) => <Tag color={row.status === 'pending' ? 'blue' : 'default'}>
          {APPROVAL_TASK_STATUS[String(row.status)] ?? String(row.status)}</Tag> },
      { title: '操作', valueType: 'option', render: (_, row) => [
        <Button key="detail" type="link" onClick={() => openDocument(row)}>查看单据</Button>,
        <Button key="yes" type="link" onClick={() => decide(row, 'approve')}>同意</Button>,
        <Button key="no" type="link" danger onClick={() => decide(row, 'reject')}>驳回</Button>,
      ] },
    ]} />
    <Modal title={detailType === 'sales_order' ? '销售订单审批详情' : '盘点审批详情'} className="psi-editor-modal" width="80%"
      open={!!detail} onCancel={() => setDetail(null)} destroyOnHidden
      footer={<Button onClick={() => setDetail(null)}>关闭</Button>}>
      {detail && <div className="page-stack"><Descriptions bordered size="small" column={2}
        items={Object.entries(detail).filter(([key, value]) => !Array.isArray(value) && !HIDDEN_DETAIL_FIELDS.has(key))
          .map(([key, value]) => ({
            key, label: FIELD_LABELS[key] ?? key,
            children: typeof value === 'boolean' ? (value ? '是' : '否') : String(value ?? '—'),
          }))} />
        <ApprovalProgress documentType={detailType as 'sales_order' | 'stocktake'} documentId={String(detail.id)} />
        <Typography.Title level={5}>单据明细</Typography.Title>
        <Table size="small" rowKey="id" dataSource={detail.lines as Row[] | undefined} pagination={false} scroll={{ x: 'max-content' }}
          columns={Array.from(new Set(((detail.lines ?? []) as Row[]).flatMap((line) => Object.keys(line))))
            .filter((key) => !HIDDEN_DETAIL_FIELDS.has(key))
            .map((key) => ({ title: FIELD_LABELS[key] ?? key, dataIndex: key,
              render: (value: unknown) => (typeof value === 'boolean' ? (value ? '是' : '否') : String(value ?? '—')) }))} />
      </div>}
    </Modal>
  </div>;
}

function Alerts() {
  const query = useQuery({ queryKey: ['alerts'], queryFn: () => get<Row[]>('/api/workbench/alerts') });
  const [filters, setFilters] = useState<FilterValues>({});
  const rows = (query.data ?? []).filter((row) => matchesKeyword(row, filters.keyword ?? '') &&
    (!filters.code || String(row.code ?? '').toLocaleLowerCase().includes(filters.code.trim().toLocaleLowerCase())));
  return <div className="workbench-tab-panel"><ListFilterBar fields={[{ key: 'keyword', label: '关键词' }, { key: 'code', label: '预警类型' }]} onApply={setFilters} />
    <ProTable<Row> rowKey={(_, index) => String(index)} search={false}
    headerTitle="预警列表"
    dataSource={rows} loading={query.isPending} pagination={{ pageSize: 20 }}
    toolBarRender={() => [<Button key="reload" onClick={() => query.refetch()}>刷新</Button>]}
    columns={[{ title: '类型', dataIndex: 'code' }, { title: '说明', dataIndex: 'detail', ellipsis: true },
      { title: '需求量', dataIndex: 'demand_quantity_base' }, { title: '可用量', dataIndex: 'available_quantity_base' },
      { title: '缺量', dataIndex: 'shortage_quantity_base' }, { title: '关联单据', dataIndex: 'document_id', ellipsis: true }]} />
  </div>;
}

export function Workbench({ access }: { access: WorkbenchAccess }) {
  const tabs = [
    ...(access.tasks ? [{ key: 'tasks', label: '我的待办', children: <Tasks /> }] : []),
    ...(access.alerts ? [{ key: 'alerts', label: '预警提醒', children: <Alerts /> }] : []),
  ];
  const [activeTab, setActiveTab] = useState(access.tasks ? 'tasks' : 'alerts');
  const openTasks = () => {
    setActiveTab('tasks');
    document.getElementById('workbench-inbox')?.scrollIntoView({ block: 'start' });
  };
  return <PageContainer title="工作台">
    {access.overview && <Overview onOpenTasks={access.tasks ? openTasks : undefined} />}
    {tabs.length > 0 && <section className="workbench-inbox" id="workbench-inbox" aria-label="待办与预警">
      <div className="workbench-inbox-heading"><span className="overview-section-kicker">ACTION CENTER</span><h2>待办与预警</h2><p>需要处理的事项，集中在这里。</p></div>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabs} />
    </section>}
  </PageContainer>;
}

