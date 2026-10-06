/** purchase 模块的页面配置。 */
import type { ResourceConfig } from '../components/resource';
import { text, number, lookup, date, remark, docColumns, itemLine, linkedLine, postActions } from './factories';
import type { Row } from '../api/client';

export const purchaseResources: Record<string, ResourceConfig> = {
  'purchase.orders': {
    title: '采购订单', endpoint: '/api/purchase/orders', menuCode: 'purchase.orders',
    // 不显示「状态」列（草稿/进行中/已关闭）：它只在「能不能改单」「还能不能收货」时才有用，
    // 而这两件事从操作列就看得出来（草稿才有编辑/删除/生效，已关闭没有任何按钮）；
    // 业务上要看的是「入库状态」，入满也不会自动结束订单，收尾靠人工强制关闭。
    columns: [{ key: 'document_no', title: '单号' }, { key: 'document_date', title: '日期' },
      { key: 'supplier_id', title: '供应商', lookup: 'parties' },
      { key: 'unreceived_quantity_base', title: '入库状态', zeroTag: { zero: '已入完', nonzero: '未入完' } }],
    // 单号可留空：后端按 CG+日期+流水生成。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      { ...lookup('supplier_id', '供应商', 'parties'), partyType: 'supplier' }, remark],
    lines: [{ name: 'lines', label: '订单明细', fields: [...itemLine, number('unit_price', '单价')] }],
    actions: [{ key: 'open', label: '生效', statuses: ['draft'] }, { key: 'close', label: '强制关闭', statuses: ['open'], prompt: 'remark', danger: true }],
    allowCreate: true, allowEdit: true, allowDelete: true,
    autoNumberPrefix: 'CG', autoNumberLabel: '采购单号',
  },
  'purchase.receipts': {
    title: '采购入库', endpoint: '/api/purchase/receipts', menuCode: 'purchase.receipts',
    columns: [...docColumns, { key: 'purchase_order_id', title: '采购订单', lookup: 'purchaseOrders' }, { key: 'warehouse_id', title: '入库仓', lookup: 'warehouses' }],
    // 单号可留空：后端按 CR+日期+流水生成。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      // 只列进行中且还有未入库量的采购订单（草稿/已关闭、已入完的都不出现）。
      { ...lookup('purchase_order_id', '采购订单', 'purchaseOrders'),
        filter: (row) => row.status === 'open'
          && Array.isArray(row.lines)
          && row.lines.some((line) => Number((line as Row).unreceived_quantity_base ?? 0) > 0) },
      lookup('warehouse_id', '入库仓库', 'warehouses'), remark],
    lines: [{ name: 'lines', label: '入库明细', fields: linkedLine('purchase_order_line_id', '订单明细', 'purchase_order_id', '/api/purchase/orders', 'lines',
      // 只读：物料由订单行决定，显示名称（编码见「订单明细」列）。
      [{ name: 'item_label', label: '物料', kind: 'item', itemSource: 'item_id' }]) }],
    actions: postActions, allowCreate: true, allowEdit: true, allowDelete: true,
    autoNumberPrefix: 'CR', autoNumberLabel: '入库单号',
  },
  'purchase.returns': {
    title: '采购退货', endpoint: '/api/purchase/returns', menuCode: 'purchase.returns',
    columns: [...docColumns, { key: 'original_receipt_id', title: '原入库单', lookup: 'purchaseReceipts' }, { key: 'warehouse_id', title: '退货仓', lookup: 'warehouses' }],
    // 单号可留空：后端按 CT+日期+流水生成。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      lookup('original_receipt_id', '原入库单', 'purchaseReceipts'), lookup('warehouse_id', '退货仓库', 'warehouses'), remark],
    lines: [{ name: 'lines', label: '退货明细', fields: linkedLine('purchase_receipt_line_id', '原入库明细', 'original_receipt_id', '/api/purchase/receipts', 'lines',
      // 只读：物料由原入库行决定，显示名称（编码见「原入库明细」列）。
      [{ name: 'item_label', label: '物料', kind: 'item', itemSource: 'item_id' }]) }],
    actions: postActions, allowCreate: true, allowEdit: true, allowDelete: true,
    autoNumberPrefix: 'CT', autoNumberLabel: '退货单号', wideModal: true,
  },
};
