/** sales 模块的页面配置。 */
import type { ResourceConfig } from '../components/resource';
import { text, number, lookup, date, remark, docColumns, itemLine, sourceLine, linkedLine, postActions } from './factories';

export const salesResources: Record<string, ResourceConfig> = {
  'sales.orders': {
    title: '销售订单', endpoint: '/api/sales/orders', menuCode: 'sales.orders',
    // 详情里显示逐级审批进度（后端 approval instances）。
    approvalType: 'sales_order',
    // 销售订单有审批流，状态列叫「审批状态」；列序为 客户 在前、审批状态 在后。
    columns: [{ key: 'document_no', title: '单号' }, { key: 'document_date', title: '日期' },
      { key: 'customer_id', title: '客户', lookup: 'parties' },
      { key: 'status', title: '审批状态' },
      // 出库/退货会改这个数：0 = 已发完。列表上直接看得出订单履约到哪一步。
      { key: 'unshipped_quantity_base', title: '发货状态', zeroTag: { zero: '已发完', nonzero: '未发完' } }],
    fields: [date(), { ...lookup('customer_id', '客户', 'parties'), partyType: 'customer' }, { name: 'delivery_date', label: '交货日期', kind: 'date' }, remark],
    lines: [{ name: 'lines', label: '订单明细', fields: [...itemLine, number('unit_price', '单价')] }],
    autoNumberPrefix: 'XS', inlineLines: true,
    actions: [{ key: 'submit', label: '提交审批', statuses: ['draft', 'rejected'], permission: 'post' }, { key: 'close', label: '强制结束', statuses: ['approved'], prompt: 'remark', danger: true }],
    allowCreate: true, allowEdit: true, allowDelete: true,
  },
  'sales.shipments': {
    title: '销售出库', endpoint: '/api/sales/shipments', menuCode: 'sales.shipments',
    columns: [...docColumns, { key: 'sales_order_id', title: '销售订单', lookup: 'salesOrders' }, { key: 'warehouse_id', title: '出库仓', lookup: 'warehouses' }],
    // 单号可留空：后端按 XC+日期+流水生成。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      // 只列还发得动的订单：已审批且仍有未发数量（草稿/待审批/已驳回/已关闭、已发完的都不出现）。
      { ...lookup('sales_order_id', '销售订单', 'salesOrders'),
        filter: (row) => row.status === 'approved' && Number(row.unshipped_quantity_base ?? 0) > 0 },
      lookup('warehouse_id', '出库仓库', 'warehouses'),
      { name: 'shipment_type', label: '出库类型', kind: 'select', required: true, choices: [{ value: 'normal', label: '普通发货' }, { value: 'replacement', label: '退货补发' }] },
      { ...lookup('replacement_return_id', '补发对应退货单', 'salesReturns', false), showWhen: { name: 'shipment_type', equals: 'replacement' } }, remark],
    lines: [{ name: 'lines', label: '出库明细', fields: [...linkedLine('sales_order_line_id', '订单明细', 'sales_order_id', '/api/sales/orders', 'lines',
      // 只读：物料由订单行决定，显示编码 · 名称。
      [{ name: 'item_label', label: '物料', kind: 'item', itemSource: 'item_id' }]),
      // 只读提示：按本单仓库 + 本行物料显示当前基本单位结存，便于判断能不能发这么多。
      { name: 'available_stock', label: '可用库存', kind: 'stock', stockItem: 'item_id', stockWarehouse: 'warehouse_id' },
      { ...sourceLine('replacement_return_line_id', '补发对应退货明细', 'replacement_return_id', '/api/sales/returns', 'lines', false),
        showWhen: { name: 'shipment_type', equals: 'replacement' } }] }],
    actions: postActions, allowCreate: true, allowEdit: true, allowDelete: true, initialValues: { shipment_type: 'normal' },
    autoNumberPrefix: 'XC', autoNumberLabel: '出库单号', wideModal: true,
    createTransform: (values) => ({ ...values, lines: (values.lines as Record<string, unknown>[]).map((line) => ({
      ...line, replacement_return_line_id: values.shipment_type === 'replacement' ? line.replacement_return_line_id : null,
    })) }),
    editTransform: (values) => ({ ...values, lines: (values.lines as Record<string, unknown>[]).map((line) => ({
      ...line, replacement_return_line_id: values.shipment_type === 'replacement' ? line.replacement_return_line_id : null,
    })) }),
  },
  'sales.returns': {
    title: '销售退货', endpoint: '/api/sales/returns', menuCode: 'sales.returns',
    columns: [...docColumns, { key: 'original_shipment_id', title: '原出库单', lookup: 'salesShipments' }, { key: 'target_warehouse_id', title: '入库仓', lookup: 'warehouses' }],
    // 单号可留空：后端按 XT+日期+流水生成。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      lookup('original_shipment_id', '原出库单', 'salesShipments'), lookup('target_warehouse_id', '退回仓库', 'warehouses'), remark],
    lines: [{ name: 'lines', label: '退货明细', fields: linkedLine('sales_shipment_line_id', '原出库明细', 'original_shipment_id', '/api/sales/shipments', 'lines',
      // 只读：物料由原出库行决定，显示名称（编码见「原出库明细」列）。
      [{ name: 'item_label', label: '物料', kind: 'item', itemSource: 'item_id' }]) }],
    actions: postActions, allowCreate: true, allowEdit: true, allowDelete: true,
    autoNumberPrefix: 'XT', autoNumberLabel: '退货单号', wideModal: true,
  },
};
