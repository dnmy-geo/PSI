import { useMemo, useRef, useState } from 'react';
import type { Key } from 'react';
import { Alert, App as AntApp, Button, Descriptions, Input, Modal, Popconfirm, Space, Switch, Table, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { ModalForm, PageContainer, ProFormList, ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { get, getPage, post, put, remove, type Row } from '../../api/client';
import { ListFilterBar, type FilterValues } from '../ListFilterBar';
import { getAllPages, matchesDateRange, matchesKeyword } from '../../utils/listFilters';
import { ApprovalProgress } from '../ApprovalProgress';
import { FIELD_LABELS, HIDDEN_DETAIL_FIELDS, VALUE_LABELS, statusLabels } from './constants';
import { Field, SourceLineCell } from './fields';
import { useLabels } from './labels';
import type { ActionSpec, Lookup, ResourceConfig } from './types';

function statusTag(status: unknown) {
  const value = String(status ?? '');
  const color = value === 'posted' || value === 'approved' || value === 'completed' ? 'green'
    : value === 'draft' ? 'default' : value === 'reversed' || value === 'cancelled' || value === 'rejected' ? 'red' : 'blue';
  return <Tag color={color}>{(statusLabels[value] ?? value) || '—'}</Tag>;
}

/**
 * antd 只在行「没有 children 这个键」时才按叶子渲染；空数组会让它画一个点了没反应的展开图标。
 * 后端统一带 children: []，所以这里把空的去掉。
 */
function stripEmptyChildren(rows: Row[]): Row[] {
  return rows.map((row) => {
    const children = row.children as Row[] | undefined;
    if (!children) return row;
    if (!children.length) {
      const copy = { ...row };
      delete copy.children;
      return copy;
    }
    return { ...row, children: stripEmptyChildren(children) };
  });
}

/** 树形列表要展开到任意深度，所以逐层收集带子节点的行键，不能只看第一层。 */
function collectExpandableKeys(rows: Row[], keyField: string): string[] {
  return rows.flatMap((row) => {
    const children = (row.children as Row[] | undefined) ?? [];
    return children.length ? [String(row[keyField]), ...collectExpandableKeys(children, keyField)] : [];
  });
}

/**
 * PUT 接口普遍要求完整对象（如 DepartmentWrite 的 code/name 必填），因此开关需带该行其余字段做增量更新。
 * 注意只覆盖扁平资源：列表行不带明细，带 lines 的资源（如 BomWrite 的 lines 必填）在这里凑不出完整请求，
 * 这类资源不应使用 toggle 开关，改用专门的动作。
 */
function incrementalBody(config: ResourceConfig, row: Row): Row {
  const body: Row = {};
  for (const field of config.fields ?? []) {
    if (field.kind === 'hidden' || field.hiddenOnEdit) continue;
    if (field.name in row) body[field.name] = row[field.name];
  }
  return body;
}

function ActiveToggle({ row, fieldKey, endpoint, canToggle, buildBody, refresh }: {
  row: Row; fieldKey: string; endpoint: string; canToggle: boolean;
  buildBody: (value: boolean) => Row; refresh: () => void;
}) {
  const { message } = AntApp.useApp();
  const [busy, setBusy] = useState(false);
  return <Switch size="small" aria-label="启用" checked={Boolean(row[fieldKey])} loading={busy} disabled={!canToggle}
    onChange={async (next) => {
      setBusy(true);
      try {
        await put(`${endpoint}/${row.id}`, buildBody(next));
        message.success(next ? '已启用' : '已停用');
        refresh();
      } catch (error) {
        message.error((error as Error).message);
      } finally {
        setBusy(false);
      }
    }} />;
}

function ActionButton({ spec, row, endpoint, refresh }: { spec: ActionSpec; row: Row; endpoint: string; refresh: () => void }) {
  const { modal, message } = AntApp.useApp();
  const [busy, setBusy] = useState(false);
  // 失败返回错误文案而不抛出：antd 在确认框 onOk 拒绝时会再抛出一个无人接管的 promise，
  // 控制台会出现未处理异常。改为「关闭旧弹窗、带着错误重开」，弹窗效果不变且没有异常。
  const run = async (body?: Row): Promise<string | null> => {
    setBusy(true);
    try {
      await post(`${endpoint}/${row.id}/${spec.path ?? spec.key}`, body);
      message.success(`${spec.label}成功`); refresh();
      return null;
    } catch (error) {
      const text = (error as Error).message;
      message.error(text);
      return text;
    } finally { setBusy(false); }
  };
  const askWithNote = (note: string, failure?: string) => {
    let current = note;
    modal.confirm({ title: `${spec.label} · ${String(row.document_no ?? row.name ?? '')}`,
      content: <div className="page-stack">
        {failure && <Alert type="error" showIcon message={failure} />}
        <Input.TextArea defaultValue={note} placeholder={spec.prompt === 'reason' ? '请填写冲销原因' : '请填写备注'}
          onChange={(event) => { current = event.target.value; }} rows={3} />
      </div>,
      okText: '确定', okButtonProps: { danger: spec.danger },
      onOk: async () => {
        if (!current.trim()) { message.warning('内容不能为空'); askWithNote(current, '内容不能为空'); return; }
        const failed = await run({ [spec.prompt!]: current.trim() });
        if (failed) askWithNote(current, failed);
      },
    });
  };
  const askDanger = (failure?: string) => modal.confirm({
    title: `确定${spec.label}吗？`, content: <div className="page-stack">
      {failure && <Alert type="error" showIcon message={failure} />}
      <span>{String(row.document_no ?? row.name ?? '')}</span>
    </div>,
    okButtonProps: { danger: true },
    onOk: async () => { const failed = await run(); if (failed) askDanger(failed); },
  });
  const execute = () => {
    if (spec.prompt && spec.prompt !== 'none') askWithNote('');
    else if (spec.danger) askDanger();
    else void run();
  };
  return <Button type="link" danger={spec.danger} size="small" loading={busy} onClick={execute}>{spec.label}</Button>;
}

/**
 * 只有元素是对象的数组才是「明细」，才按表格渲染。
 * 字符串数组（role_ids、往来单位 types）交给表格会把字符串拆成字符下标当表头。
 */
const isDetailRows = (value: unknown) =>
  Array.isArray(value) && value.some((item) => typeof item === 'object' && item !== null);

export function ResourcePage({ config }: { config: ResourceConfig }) {
  const { message } = AntApp.useApp();
  const table = useRef<ActionType>();
  const labels = useLabels(config);
  const permissions = useQuery({ queryKey: ['my-permissions'], queryFn: () => get<Record<string, string[]>>('/api/system/my-permissions') });
  const can = (action: string) => (permissions.data?.[config.menuCode] ?? []).includes(action);
  const [editing, setEditing] = useState<Row | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [detail, setDetail] = useState<Row | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [filters, setFilters] = useState<FilterValues>({});
  // 列表接口返回 created_at/updated_at 时才补这两列（库存结存、工作台等没有这两列的列表不受影响）。
  const [showTimestamps, setShowTimestamps] = useState(false);
  // 树形列表默认展开：defaultExpandAllRows 对异步加载的数据不生效，改为数据到达后主动展开。
  const [expandedKeys, setExpandedKeys] = useState<readonly Key[]>([]);
  const reload = () => { table.current?.reload(); labels.refresh(); };
  const fieldLabel = (key: string) => config.fields?.find((field) => field.name === key)?.label
    ?? config.columns.find((column) => column.key === key)?.title
    ?? FIELD_LABELS[key]
    ?? key;
  // 明细列的标题：明细字段自己的 label 最准；其次是派生列的通用中文名；
  // 最后才回退到列表列名——列表列标题可能与明细字段同名不同义（如列表的「发货状态」）。
  const lineLabel = (key: string) => [...(config.lines ?? []), ...(config.detailLines ?? [])].flatMap((group) => group.fields)
    .find((field) => field.name === key)?.label
    ?? FIELD_LABELS[key]
    ?? config.columns.find((column) => column.key === key)?.title
    ?? key;
  const ISO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;
  const formatValue = (key: string, value: unknown, lookup?: Lookup) => {
    if (key === 'status') return statusTag(value);
    // 接口给的是 ISO 时间串（created_at/updated_at/posted_at…），详情里统一格式化。
    if (typeof value === 'string' && ISO_TIMESTAMP.test(value)) return dayjs(value).format('YYYY-MM-DD HH:mm:ss');
    if (typeof value === 'boolean') return value ? '是' : '否';
    // 下拉字段在详情里只显示存的值（如 item_type 会露出 raw_material），先按选项表翻一遍。
    const choice = config.fields?.find((field) => field.name === key)?.choices
      ?.find((option) => option.value === value);
    if (choice) return choice.label;
    return VALUE_LABELS[String(value)] ?? labels.display(value,
      lookup ?? (key === 'item_id' ? 'items' : key === 'unit_id' ? 'units' : undefined));
  };
  const openDetail = async (row: Row) => {
    try { setDetail(config.detailFromList ? row : await get<Row>(`${config.detailEndpoint ?? config.endpoint}/${row.id}`)); setDetailOpen(true); }
    catch (error) { message.error((error as Error).message); }
  };
  const isResourceRow = (row: Row) => !config.tree || config.tree.isResourceRow(row);
  const columns: ProColumns<Row>[] = config.columns.map((column) => ({
    title: column.title, dataIndex: column.key, ellipsis: true, search: false,
    ...(column.width ? { width: column.width } : column.toggle ? { width: 96 } : {}),
    render: (_, row) => {
      if (column.toggle) {
        // 树形列表展开出来的子行没有自己的单据，toggleWhen 为假的行（如系统保留角色）后端也不允许改，
        // 这两种情况都只显示状态，不给一个点了必报错的开关。
        const toggleable = isResourceRow(row) && (!column.toggleWhen || column.toggleWhen(row));
        if (toggleable) {
          return <ActiveToggle row={row} fieldKey={column.key} endpoint={config.endpoint} refresh={reload}
            canToggle={can(config.writePermissions?.update ?? 'update')}
            buildBody={(value) => {
              const body = incrementalBody(config, row);
              body[column.key] = value;
              return config.editTransform?.(body, row) ?? body;
            }} />;
        }
        return isResourceRow(row)
          ? <Tag color={row[column.key] ? 'green' : 'default'}>{row[column.key] ? '是' : '否'}</Tag>
          : null;
      }
      if (column.key === 'status') return statusTag(row[column.key]);
      if (column.arrayField) {
        const items = (row[column.key] as Row[] | undefined) ?? [];
        return items.length ? items.map((item) => String(item[column.arrayField!] ?? '')).join('、') : '—';
      }
      // 树形列表展开出来的子行没有自己的单据，也就没有启用状态，留空而不是显示「否」。
      if (column.zeroTag) {
        const value = Number(row[column.key] ?? 0);
        return <Tag color={value === 0 ? 'green' : 'blue'}>{value === 0 ? column.zeroTag.zero : column.zeroTag.nonzero}</Tag>;
      }
      if (column.flag) {
        return isResourceRow(row)
          ? <Tag color={row[column.key] ? 'green' : 'default'}>{row[column.key] ? '是' : '否'}</Tag>
          : null;
      }
      // 数量按各物料自己的基本单位计量，所以要逐行带上单位。
      if (column.unitKey) {
        const unit = row[column.unitKey];
        return row[column.key] == null ? '—'
          : `${labels.display(row[column.key])}${unit ? ` ${String(unit)}` : ''}`;
      }
      // 枚举列（如物料类型 raw_material）按同名字段上的 choices 翻成中文，
      // 否则列表里只有这一处露原始值，表单和详情都是中文。
      const choice = config.fields?.find((field) => field.name === column.key)?.choices
        ?.find((option) => option.value === row[column.key]);
      if (choice) return choice.label;
      return labels.display(row[column.key], column.lookup);
    },
  }));
  const dateColumn = config.columns.find((column) => ['document_date', 'effective_date', 'created_at', 'posted_at'].includes(column.key));
  const filterFields = [
    { key: 'keyword', label: '关键词' },
    ...(config.columns.some((column) => column.key === 'status') ? [{ key: 'status', label: '状态', kind: 'select' as const,
      options: Object.entries(statusLabels).map(([value, label]) => ({ value, label })) }] : []),
    ...(dateColumn ? [{ key: 'date', label: dateColumn.title, kind: 'dateRange' as const }] : []),
  ];
  const hasFilters = Object.values(filters).some(Boolean);
  const matchesRow = (row: Row) => {
    const displayed = Object.fromEntries(config.columns.map((column) => [column.key, labels.display(row[column.key], column.lookup)]));
    return matchesKeyword(displayed, filters.keyword ?? '') &&
      (!filters.status || String(row.status ?? '').toLocaleLowerCase().includes(filters.status.trim().toLocaleLowerCase())) &&
      (!dateColumn || matchesDateRange(row[dateColumn.key], filters.dateFrom, filters.dateTo));
  };
  const timeColumn = (key: 'created_at' | 'updated_at', title: string): ProColumns<Row> => ({
    title, dataIndex: key, width: 175, search: false,
    render: (_, row) => row[key] ? dayjs(String(row[key])).format('YYYY-MM-DD HH:mm:ss') : '—',
  });
  if (showTimestamps) columns.push(timeColumn('created_at', '创建时间'), timeColumn('updated_at', '修改时间'));
  columns.push({ title: '操作', valueType: 'option', width: 320, fixed: 'right',
    render: (_, row) => !isResourceRow(row) ? null : <Space size={0} wrap>
    <Button type="link" size="small" onClick={() => openDetail(row)}>详情</Button>
    {config.allowEdit && can(config.writePermissions?.update ?? 'update') && (!row.status || row.status === 'draft' || row.status === 'rejected') &&
      <Button type="link" size="small" onClick={async () => {
        try { setEditing(config.detailFromList ? row : await get<Row>(`${config.detailEndpoint ?? config.endpoint}/${row.id}`)); setFormOpen(true); }
        catch (error) { message.error((error as Error).message); }
      }}>编辑</Button>}
    {config.actions?.filter((action) => !(action.key === 'reverse' && row.is_opening_reference) && can(action.permission ?? (action.key === 'close' && config.menuCode !== 'production.plans' ? 'force_close' : action.key === 'reverse' ? 'reverse' : action.key === 'submit' ? 'submit' : 'post')) && (!action.statuses || action.statuses.includes(String(row.status)))).map((action) =>
      <ActionButton key={action.key} spec={action} row={row} endpoint={config.endpoint} refresh={reload} />)}
    {config.customAction?.(row, reload, can)}
    {config.allowDelete && can(config.writePermissions?.delete ?? 'delete') && (!row.status || row.status === 'draft' || row.status === 'rejected') &&
      <Popconfirm title="确定删除吗？" description={config.endpoint === '/api/parties' && Array.isArray(row.types) && row.types.length > 1
        ? '这个往来单位具有多种身份，删除会同时影响客户、供应商或加工商身份。' : undefined} onConfirm={async () => {
        try { await remove(`${config.endpoint}/${row.id}`); message.success('已删除'); reload(); }
        catch (error) { message.error((error as Error).message); }
      }}><Button type="link" danger size="small">删除</Button></Popconfirm>}
  </Space> });

  const initialValues = useMemo(() => {
    const values = { ...config.initialValues, ...editing };
    for (const field of config.fields ?? []) {
      if (!editing && field.name === 'document_date' && field.kind === 'date' && !values[field.name]) {
        values[field.name] = dayjs();
      }
      if (field.kind === 'date' && values[field.name] && !dayjs.isDayjs(values[field.name])) {
        values[field.name] = dayjs(String(values[field.name]));
      }
    }
    return values;
  }, [config.fields, config.initialValues, editing]);
  const hasDocumentNumber = !!config.autoNumberPrefix || (config.fields ?? []).some((field) => field.name === 'document_no');
  const visibleFields = (config.fields ?? []).filter((field) => field.kind !== 'hidden' && !(editing && field.hiddenOnEdit));
  const primaryFields = visibleFields.filter((field) => field.name !== 'remark');
  const noteFields = visibleFields.filter((field) => field.name === 'remark');
  const hiddenFields = (config.fields ?? []).filter((field) => field.kind === 'hidden');
  const formSubtitle = hasDocumentNumber
    ? '先填写单据基本信息，再核对业务明细。保存后可在列表中继续处理。'
    : '填写基础信息并检查必填项，保存后即可在列表中查看。';
  return <PageContainer title={config.title}>
    <ListFilterBar fields={filterFields} onApply={setFilters} />
    <ProTable<Row> key={JSON.stringify(filters)} actionRef={table} columns={columns} scroll={{ x: 'max-content' }}
      rowKey={config.tree ? config.tree.rowKey : 'id'}
      expandable={config.tree ? { expandedRowKeys: expandedKeys, onExpandedRowsChange: setExpandedKeys } : undefined}
      onLoad={(rows) => {
        if (config.tree) setExpandedKeys(collectExpandableKeys(rows, config.tree.rowKey));
        setShowTimestamps(rows.some((row) => row.created_at || row.updated_at));
      }}
      headerTitle={`${config.title}列表`} locale={{ emptyText: `暂无${config.title}记录` }}
      search={false} pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100] }}
      request={async (params) => {
        const page = params.current ?? 1;
        const size = params.pageSize ?? 10;
        const shape = (rows: Row[]) => config.tree ? stripEmptyChildren(rows) : rows;
        if (hasFilters) {
          const rows = config.serverPaging ? await getAllPages(config.endpoint, config.listParams)
            : await get<Row[]>(config.endpoint, { ...config.listParams });
          const filtered = rows.filter(matchesRow);
          return { data: shape(filtered.slice((page - 1) * size, page * size)), success: true, total: filtered.length };
        }
        if (config.serverPaging) {
          const { data, total } = await getPage<Row[]>(config.endpoint, { limit: size, offset: (page - 1) * size, ...config.listParams });
          return { data: shape(data), success: true, total };
        }
        return { data: shape(await get<Row[]>(config.endpoint, { ...config.listParams })), success: true };
      }}
      toolBarRender={() => config.allowCreate && can(config.writePermissions?.create ?? 'create') ? [<Button key="create" type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setFormOpen(true); }}>新建{config.title}</Button>] : []}
    />
    <ModalForm<Row> key={`${config.menuCode}-${editing?.id ?? 'new'}`} title={editing ? `编辑${config.title}` : `新建${config.title}`}
      open={formOpen} onOpenChange={setFormOpen}
      width={config.modalWidth ?? (config.inlineLines || config.wideModal ? 1100 : hasDocumentNumber || !!config.lines?.length ? 920 : 680)}
      modalProps={{ className: 'psi-editor-modal', destroyOnHidden: true }}
      initialValues={initialValues}
      onFinish={async (values) => {
        try {
          const normalized = { ...values };
          for (const field of config.fields ?? []) {
            const value = normalized[field.name];
            if (field.kind === 'date' && dayjs.isDayjs(value)) {
              normalized[field.name] = value.format('YYYY-MM-DD');
            }
          }
          const body = editing ? (config.editTransform?.(normalized, editing) ?? normalized) : (config.createTransform?.(normalized) ?? normalized);
          if (editing) await put(`${config.endpoint}/${editing.id}`, body);
          else await post(config.endpoint, body);
          message.success('保存成功'); reload(); return true;
        } catch (error) { message.error((error as Error).message); return false; }
      }}>
      <div className="psi-editor-intro">
        <span className="psi-editor-kicker">{hasDocumentNumber ? 'BUSINESS DOCUMENT' : 'MASTER DATA'}</span>
        <p>{formSubtitle}</p>
      </div>
      {config.autoNumberPrefix && <div className="psi-auto-number">
        <span>{config.autoNumberLabel ?? '订单单号'}</span><strong>{editing ? String(editing.document_no) : `${config.autoNumberPrefix}年月日流水号`}</strong>
        <small>{editing ? '单号创建后保持不变' : '保存时按单据日期自动生成'}</small>
      </div>}
      {hiddenFields.map((field) => <Field key={field.name} field={field} editing={!!editing} />)}
      {primaryFields.length > 0 && <section className="psi-editor-section" aria-label="基本信息">
        <div className="psi-editor-section-heading"><span className="psi-editor-step">01</span><div><h3>基本信息</h3><p>带 * 的项目为必填项</p></div></div>
        <div className={`psi-editor-fields${config.singleColumn ? ' is-single-column' : config.threeColumn ? ' is-three-column' : ''}`}>
          {/* 开关只有 44px 宽，不必独占整行；让它和相邻字段并排，避免前面留出空格子。 */}
          {primaryFields.map((field) => <div className={`psi-editor-field${field.kind === 'textarea' || field.kind === 'multiLookup' ? ' is-wide' : ''}`} key={field.name}>
            <Field field={field} editing={!!editing} row={editing} />
          </div>)}
        </div>
      </section>}
      {config.lines?.map((group, index) => <section className={`psi-editor-section psi-editor-lines${config.inlineLines ? ' is-inline-lines' : ''}`} aria-label={group.label} key={group.name}>
        <div className="psi-editor-section-heading"><span className="psi-editor-step">{String(index + 2).padStart(2, '0')}</span><div><h3>{group.label}</h3><p>{group.optional ? '按需添加，可留空' : '至少填写一条，逐项核对物料与数量'}</p></div></div>
        <ProFormList name={group.name} label=" " min={group.optional ? 0 : 1}
          // 明细列表的必填校验放在前端：否则空明细会直接提交，用户只会看到后端按字段名报的「lines：必填项没有填写」。
          isValidateList={!group.optional}
          emptyListMessage={`请至少添加一条${group.label}`}
          creatorButtonProps={{ creatorButtonText: `添加${group.label}` }}>
          {(meta, _index, action) => <div className="psi-editor-line-grid">
            {group.fields.map((field) => <div className={`psi-editor-line-field${field.kind === 'hidden' ? ' is-hidden' : ''}`} key={field.name}>
              <Field field={field} editing={!!editing} setCurrentRowData={action.setCurrentRowData}
                rowPathPrefix={[group.name, Number(meta?.name ?? 0)]} />
            </div>)}
          </div>}
        </ProFormList>
      </section>)}
      {noteFields.length > 0 && <section className="psi-editor-section psi-editor-note" aria-label="备注">
        <div className="psi-editor-section-heading"><span className="psi-editor-step">{String((config.lines?.length ?? 0) + 2).padStart(2, '0')}</span><div><h3>备注</h3><p>补充需要交接或说明的信息</p></div></div>
        {noteFields.map((field) => <Field key={field.name} field={field} editing={!!editing} />)}
      </section>}
    </ModalForm>
    {/* 复用编辑弹窗的样式（含 max-height + 内部滚动），详情和编辑的观感保持一致。 */}
    <Modal title={`${config.title}详情`} className="psi-editor-modal" width="80%" open={detailOpen}
      onCancel={() => setDetailOpen(false)} destroyOnHidden
      footer={<Button onClick={() => setDetailOpen(false)}>关闭</Button>}>
      {detail && <div className="page-stack">
        <Descriptions bordered size="small" column={2}>
          {Object.entries(detail).filter(([key, value]) => !HIDDEN_DETAIL_FIELDS.has(key)
            // 列表里的派生状态列（zeroTag，如「发货状态」「入库状态」）不在详情里重复：
            // 它只是把某个数量压成中文标签，详情要看的是原始数量，而原始数量在明细表里逐行给。
            && !config.columns.some((column) => column.key === key && column.zeroTag)
            && !isDetailRows(value) && (typeof value !== 'object' || Array.isArray(value))).map(([key, value]) =>
            <Descriptions.Item key={key} label={fieldLabel(key)} span={key === 'remark' ? 2 : 1}>
              <Typography.Text copyable={key === 'id'}>{formatValue(key, value, config.fields?.find((field) => field.name === key)?.lookup ?? config.columns.find((column) => column.key === key)?.lookup)}</Typography.Text>
            </Descriptions.Item>)}
        </Descriptions>
        {config.approvalType && <ApprovalProgress documentType={config.approvalType} documentId={String(detail.id)} />}
        {Object.entries(detail).filter(([, value]) => isDetailRows(value)).map(([key, value]) => {
          const rows = value as Row[];
          // 明细组既可能在 lines（表单里维护），也可能只在 detailLines（由别的入口维护，如拆单产出）。
          const group = [...(config.lines ?? []), ...(config.detailLines ?? [])].find((entry) => entry.name === key);
          // 明细行的 id 同样是裸 UUID，不展示；rowKey 仍用它，只是不进列。
          const declared = group?.fields.map((field) => field.name) ?? [];
          const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row))))
            .filter((column) => !HIDDEN_DETAIL_FIELDS.has(column))
            // 配置声明过的字段按声明顺序排（和表单里的顺序一致），接口多返回的派生列按原顺序追加在后面。
            .sort((left, right) => {
              const a = declared.indexOf(left); const b = declared.indexOf(right);
              return (a < 0 ? declared.length : a) - (b < 0 ? declared.length : b);
            });
          return <div key={key}><Typography.Title level={5}>{group?.label ?? key}</Typography.Title>
            <Table size="small" rowKey={(row) => String(row.id ?? JSON.stringify(row))} dataSource={rows} pagination={false} scroll={{ x: 'max-content' }}
              // 明细列同样走 fieldLabel：接口会多返回几个配置里没声明的派生列（如 allocated_quantity_base），
              // 直接拿 key 当表头就是英文。
              columns={keys.map((column) => {
                const spec = group?.fields.find((field) => field.name === column);
                return {
                  title: spec?.label ?? lineLabel(column), dataIndex: column,
                  render: (cell: unknown) => spec?.kind === 'sourceLine' && spec.source
                    // 来源行外键（订单明细/原出库明细…）显示成 物料·数量
                    ? <SourceLineCell field={spec} parentId={detail[spec.source.parent]} lineId={cell} />
                    : formatValue(column, cell, spec?.lookup),
                };
              })} />
          </div>;
        })}
      </div>}
    </Modal>
  </PageContainer>;
}
