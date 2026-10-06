/** inventory 模块的页面配置。 */
import type { ResourceConfig } from '../components/resource';
import { text, number, lookup, date, remark, docColumns, docFields, itemLine, postActions } from './factories';

export const inventoryResources: Record<string, ResourceConfig> = {
  'inventory.transfers': {
    title: '仓库调拨', endpoint: '/api/inventory/transfers', menuCode: 'inventory.transfers',
    columns: [...docColumns, { key: 'source_warehouse_id', title: '来源仓', lookup: 'warehouses' }, { key: 'target_warehouse_id', title: '目标仓', lookup: 'warehouses' }],
    // 单号可留空：后端按 DB+日期+流水生成。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      lookup('source_warehouse_id', '来源仓库', 'warehouses'), lookup('target_warehouse_id', '目标仓库', 'warehouses'), remark],
    // 明细直接选物料（调拨没有来源单，物料不是从上游带出来的，和领料/消耗一致）。
    lines: [{ name: 'lines', label: '调拨明细', fields: itemLine }],
    actions: postActions, allowCreate: true,
    autoNumberPrefix: 'DB', autoNumberLabel: '调拨单号',
  },
  'inventory.adjustments': {
    title: '库存调整', endpoint: '/api/inventory/adjustments', menuCode: 'inventory.adjustments',
    columns: [...docColumns, { key: 'warehouse_id', title: '仓库', lookup: 'warehouses' }, { key: 'reason', title: '原因' }],
    fields: [...docFields, lookup('warehouse_id', '仓库', 'warehouses'), text('reason', '调整原因'), remark],
    lines: [{ name: 'lines', label: '调整明细', fields: [lookup('item_id', '物料', 'items'),
      // 盘亏要填负数：不给下限的话数字框会被库默认的 min=0 夹住（见 FieldSpec.min 注释）。
      { ...number('quantity_delta_base', '调整数量（可为负）'), min: -1000000000 }] }],
    actions: [{ ...postActions[0], permission: 'adjust' }, postActions[1]],
    allowCreate: true, allowEdit: true, allowDelete: true,
    writePermissions: { create: 'adjust', update: 'adjust', delete: 'adjust' },
  },
  'inventory.stocktakes': {
    title: '库存盘点', endpoint: '/api/inventory/stocktakes', menuCode: 'inventory.stocktakes',
    // 详情里显示逐级审批进度（与销售订单同一套，后端 /api/approval/documents/stocktake/… 支持）；
    // 没提交过审批的盘点单没有实例，组件自动不显示。
    approvalType: 'stocktake',
    columns: [...docColumns, { key: 'warehouse_id', title: '仓库', lookup: 'warehouses' }],
    // 单号可留空：后端按 PD+日期+流水生成。弹窗放宽到 80%（与详情弹窗一致）。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      lookup('warehouse_id', '仓库', 'warehouses'), remark],
    // 单号 / 单据日期 / 仓库 并排一行（备注仍独占一行）。
    threeColumn: true,
    modalWidth: '80%',
    // 实盘明细由「录入实盘数」弹窗维护，不在新建表单里；这里只声明字段，
    // 好让详情表的「物料」按字典翻译（不声明就会露出 item_id 的 UUID）。
    detailLines: [{ name: 'lines', label: '盘点明细', fields: [
      lookup('item_id', '物料', 'items'), { name: 'book_quantity_base', label: '账面数量' },
      { name: 'counted_quantity_base', label: '实盘数量' },
      { name: 'difference_quantity_base', label: '差异数量' }] }],
    actions: [{ key: 'start', label: '开始盘点', statuses: ['draft', 'rejected'], permission: 'update' }, { key: 'submit', label: '提交审批', statuses: ['counting'] }, { key: 'cancel', label: '取消', prompt: 'reason', danger: true, statuses: ['draft', 'counting', 'rejected'], permission: 'delete' }],
    allowCreate: true,
    autoNumberPrefix: 'PD', autoNumberLabel: '盘点单号',
  },
};
