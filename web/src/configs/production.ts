/** production 模块的页面配置。 */
import type { ResourceConfig } from '../components/resource';
import { text, number, integer, lookup, date, remark, status, docColumns, itemLine, sourceLine, postActions } from './factories';

export const productionResources: Record<string, ResourceConfig> = {
  'production.plans': {
    title: '生产计划', endpoint: '/api/production/plans', menuCode: 'production.plans', serverPaging: true,
    // 单据编号列单独写标签：生产条线上「单号」指代不清，写明是计划还是订单的编码。
    columns: [{ key: 'document_no', title: '生产计划编码' }, { key: 'document_date', title: '日期' }, status],
    // 编码可留空：后端按 SC+日期+流水生成。
    fields: [{ ...text('document_no', '生产计划编码', false), placeholder: '留空自动生成' }, date(), remark],
    lines: [{ name: 'lines', label: '计划产出', fields: [
      // 只给启用中的半成品/成品：后端也只接受这两种（传原材料会 422），下拉里先挡掉免得保存才报错。
      { ...lookup('item_id', '半成品或成品', 'items'),
        filter: (row) => row.is_active === true
          && (row.item_type === 'semi_finished' || row.item_type === 'finished') },
      integer('planned_quantity_base', '计划数量（整数）'),
      // 只读：计划数量按物料的基本单位计（后端存的就是基本单位整数），跟在数量后面标注，免得只剩一个裸数字。
      { name: 'unit_label', label: '单位', kind: 'unit', itemSource: 'item_id' }] }],
    actions: [{ key: 'open', label: '生效', statuses: ['draft'] }, { key: 'close', label: '结束', statuses: ['open'], danger: true }],
    allowCreate: true, allowEdit: true, allowDelete: true,
    autoNumberPrefix: 'SC', autoNumberLabel: '计划编码', modalWidth: '80%',
  },
  'production.orders': {
    title: '生产订单', endpoint: '/api/production/orders', menuCode: 'production.orders', serverPaging: true,
    columns: [{ key: 'document_no', title: '生产订单编码' }, { key: 'document_date', title: '日期' }, status,
      { key: 'production_plan_id', title: '生产计划编码', lookup: 'productionPlans' }],
    // 产出明细由拆单生成，不在表单里维护；声明字段只为让详情表翻对外键：
    // 计划行按「物料 · 数量」显示（和其他单据的来源行同一套 SourceLineCell），物料按字典显示编码·名称。
    detailLines: [{ name: 'outputs', label: '产出明细', fields: [
      sourceLine('production_plan_line_id', '计划行', 'production_plan_id', '/api/production/plans', 'lines', false),
      { name: 'item_id', label: '物料', kind: 'hidden' },
      { name: 'planned_quantity_base', label: '计划数量' },
      { name: 'unit_code', label: '单位' }] }],
    actions: [{ key: 'open', label: '开始', statuses: ['draft'] }], allowCreate: false, allowDelete: true,
  },
  'production.issues': {
    title: '生产领料', endpoint: '/api/production/issues', menuCode: 'production.issues', serverPaging: true,
    columns: [...docColumns, { key: 'production_order_id', title: '生产订单', lookup: 'productionOrders' }, { key: 'source_warehouse_id', title: '来源仓', lookup: 'warehouses' }, { key: 'target_warehouse_id', title: '现场仓', lookup: 'warehouses' }],
    // 单号可留空：后端按 SCLL+日期+流水生成。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      lookup('production_order_id', '生产订单', 'productionOrders'), lookup('source_warehouse_id', '来源仓', 'warehouses'), lookup('target_warehouse_id', '现场仓', 'warehouses'), remark],
    // 领料明细按业务要求把「单位」放在「物料」前面（仅本单据这样排；单位下拉仍按所选物料过滤）。
    lines: [{ name: 'lines', label: '领料明细', fields: [
      { ...lookup('unit_id', '单位', 'units'), unitFor: 'item_id' },
      lookup('item_id', '物料', 'items'),
      number('quantity', '数量'),
      { name: 'bom_quantity_base', label: 'BOM 用量', kind: 'number' },
      { name: 'loss_quantity_base', label: '损耗量', kind: 'number' }] }],
    actions: postActions, allowCreate: true, allowEdit: true, allowDelete: true, modalWidth: '80%',
    autoNumberPrefix: 'SCLL', autoNumberLabel: '领料单号',
  },
  'production.consumptions': {
    title: '生产消耗', endpoint: '/api/production/consumptions', menuCode: 'production.consumptions', serverPaging: true,
    columns: [...docColumns, { key: 'production_order_id', title: '生产订单', lookup: 'productionOrders' }, { key: 'warehouse_id', title: '消耗仓', lookup: 'warehouses' }],
    // 单号可留空：后端按 SCXH+日期+流水生成。明细的物料/单位直接选（消耗没有来源行）。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      lookup('production_order_id', '生产订单', 'productionOrders'), lookup('warehouse_id', '消耗仓', 'warehouses'), remark],
    lines: [{ name: 'lines', label: '消耗明细', fields: itemLine }],
    actions: postActions, allowCreate: true, allowEdit: true, allowDelete: true, modalWidth: '80%',
    autoNumberPrefix: 'SCXH', autoNumberLabel: '消耗单号',
  },
  'production.receipts': {
    title: '生产入库', endpoint: '/api/production/receipts', menuCode: 'production.receipts', serverPaging: true,
    columns: [...docColumns, { key: 'production_order_id', title: '生产订单', lookup: 'productionOrders' }],
    // 单号可留空：后端按 SCRK+日期+流水生成。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      lookup('production_order_id', '生产订单', 'productionOrders'), remark],
    lines: [{ name: 'lines', label: '产出入库', fields: [sourceLine('production_order_output_id', '生产订单产出', 'production_order_id', '/api/production/orders', 'outputs'),
      { name: 'item_id', label: '物料', kind: 'hidden' }, lookup('target_warehouse_id', '目标仓库', 'warehouses'),
      integer('quantity_base', '入库数量（整数）'),
      // 只读：入库数量按物料的基本单位计，跟在数量后面标注（与生产计划产出一致）。
      { name: 'unit_label', label: '单位', kind: 'unit', itemSource: 'item_id' }] }],
    actions: postActions, allowCreate: true, allowEdit: true, allowDelete: true, modalWidth: '80%',
    autoNumberPrefix: 'SCRK', autoNumberLabel: '入库单号',
  },
};
