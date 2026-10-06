import { useState } from 'react';
import { Tooltip } from 'antd';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import dayjs from 'dayjs';
import { getPage, type Row } from '../../api/client';
import { ListFilterBar, type FilterValues } from '../../components/ListFilterBar';
import { getAllPages, matchesDateRange, matchesKeyword } from '../../utils/listFilters';

const auditSubjects: Record<string, string> = {
  approval: '审批', approval_config: '审批配置', cash_record: '收付款', department: '部门', menu: '菜单',
  organization: '组织', outsourcing_issue: '委外发料', outsourcing_order: '委外单', outsourcing_receipt: '委外入库',
  party_opening_balance: '期初往来', opening_balance: '期初往来', production_consumption: '生产消耗',
  production_issue: '生产领料', production_order: '生产订单', production_plan: '生产计划',
  production_receipt: '生产入库', purchase_order: '采购订单', purchase_receipt: '采购入库',
  purchase_return: '采购退货', role: '角色', sales_order: '销售订单', sales_return: '销售退货',
  sales_shipment: '销售出库', stocktake: '库存盘点', user: '用户',
  // 基础资料与库存单据：动作码前缀与单据类型不完全同名（如 category ↔ item_category），
  // 名称取界面上资料页的叫法，避免日志里露出原始编码。
  bom: '用料清单', carryover: '接续业务', category: '物料分类', item: '物料', unit: '计量单位',
  party: '往来单位', warehouse: '仓库', opening_stock: '期初库存',
  stock_adjustment: '库存调整', stock_transfer: '仓库调拨',
};
// 单据类型列比动作里的对象名更正式一些，只有少数几个不同。
const auditDocumentTypes: Record<string, string> = { ...auditSubjects, role: '角色（岗位）', stocktake: '库存盘点', item_category: '物料分类' };
const auditVerbs: Record<string, string> = {
  create: '新建', update: '修改', delete: '删除', open: '开单', close: '关闭', submit: '提交',
  post: '过账', reverse: '冲销', approve: '同意', reject: '驳回', start: '开始', cancel: '取消',
  count: '录入实盘', replace: '重设', permissions: '权限', activate: '启用', deactivate: '停用',
  force_close: '强制关闭', import: '导入', reset_password: '重设密码', save: '保存',
};
function auditActionLabel(code: string): string {
  if (code === 'role.permissions.replace') return '角色 · 重设权限';
  const [subject, ...rest] = code.split('.');
  const verb = rest.join('.');
  return `${auditSubjects[subject] ?? subject} · ${auditVerbs[verb] ?? verb}`;
}

export function AuditLogsPage() {
  const [filters, setFilters] = useState<FilterValues>({});
  return <PageContainer title="操作日志"><ListFilterBar fields={[{ key: 'keyword', label: '操作、单据或人员' }, { key: 'date', label: '操作时间', kind: 'dateRange' }]} onApply={setFilters} />
    <ProTable<Row> key={JSON.stringify(filters)} rowKey="id" search={false} scroll={{ x: 'max-content' }}
    pagination={{ pageSize: 20 }}
    request={async (params) => {
      const page = params.current ?? 1; const size = params.pageSize ?? 20;
      if (Object.values(filters).some(Boolean)) {
        const rows = (await getAllPages('/api/system/audit-logs')).filter((row) =>
          matchesKeyword(row, filters.keyword ?? '', ['action_code', 'document_type', 'document_id', 'actor_name', 'reason']) &&
          matchesDateRange(row.occurred_at, filters.dateFrom, filters.dateTo));
        return { data: rows.slice((page - 1) * size, page * size), success: true, total: rows.length };
      }
      const { data, total } = await getPage<Row[]>('/api/system/audit-logs', { limit: size, offset: (page - 1) * size });
      return { data, success: true, total };
    }}
    columns={[
      // 宽度按各列实际内容定：操作人 5 字、时间固定 19 字符、操作最长 12 字（库存盘点 · 录入实盘）、
      // 单据类型未登记时会回退成原始码（最长 21 字符）、单据 ID 是 36 字符 UUID。原因基本为空，
      // 让它做唯一的弹性列吸收剩余宽度即可，不必给它固定宽度。
      { title: '操作人', dataIndex: 'actor_name', width: 110,
        render: (_, row) => String(row.actor_name ?? row.actor_id ?? '—') },
      { title: '时间', dataIndex: 'occurred_at', width: 175,
        render: (_, row) => row.occurred_at ? dayjs(String(row.occurred_at)).format('YYYY-MM-DD HH:mm:ss') : '—' },
      { title: '操作', dataIndex: 'action_code', width: 175, render: (_, row) => auditActionLabel(String(row.action_code)) },
      { title: '单据类型', dataIndex: 'document_type', width: 150,
        render: (_, row) => auditDocumentTypes[String(row.document_type)] ?? String(row.document_type ?? '—') },
      // 优先显示单号（悬浮可见完整 UUID）；解析不到单号的类型回退成截断的 UUID。
      { title: '单据', dataIndex: 'document_label', width: 200, ellipsis: true,
        render: (_, row) => <Tooltip title={String(row.document_id ?? '')}>
          <span className={row.document_label ? undefined : 'mono dim'}>
            {row.document_label ? String(row.document_label)
              : row.document_id ? `${String(row.document_id).slice(0, 8)}…` : '—'}
          </span>
        </Tooltip> },
      { title: '原因', dataIndex: 'reason', ellipsis: true },
    ]} />
  </PageContainer>;
}
