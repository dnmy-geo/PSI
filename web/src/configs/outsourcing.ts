/** outsourcing 模块的页面配置。 */
import type { ResourceConfig } from '../components/resource';
import { text, number, lookup, date, remark, docColumns, linkedLine, postActions } from './factories';

export const outsourcingResources: Record<string, ResourceConfig> = {
  'outsourcing.orders': {
    title: '委外单', endpoint: '/api/outsourcing/orders', menuCode: 'outsourcing.orders',
    columns: [...docColumns, { key: 'processor_id', title: '加工商', lookup: 'parties' }],
    // 单号可留空：后端按 WW+日期+流水生成。两处预量都按基本单位计，后面跟只读单位。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      { ...lookup('processor_id', '加工商', 'parties'), partyType: 'processor' }, remark],
    // 单号 / 单据日期 / 加工商 并排一行（备注仍独占一行）。
    threeColumn: true,
    lines: [
      { name: 'materials', label: '加工物料', optional: true, fields: [lookup('item_id', '原料', 'items'), { name: 'supply_party', label: '供料方', kind: 'select', required: true, choices: [{ value: 'self', label: '我方供料' }, { value: 'processor', label: '加工商包料' }] },
        number('expected_quantity_base', '预计用量'), { name: 'unit_label', label: '单位', kind: 'unit', itemSource: 'item_id' }] },
      // 只给启用中的半成品/成品：后端也只接受这两种（传原材料会 422），下拉里先挡掉。
      { name: 'outputs', label: '产出品', fields: [{ ...lookup('item_id', '产出物料', 'items'),
        filter: (row) => row.is_active === true
          && (row.item_type === 'semi_finished' || row.item_type === 'finished') },
        number('expected_quantity_base', '预计数量'),
        { name: 'unit_label', label: '单位', kind: 'unit', itemSource: 'item_id' }, number('unit_price', '加工单价')] },
    ],
    actions: [{ key: 'open', label: '生效', statuses: ['draft'] }, { key: 'close', label: '强制结束', statuses: ['open'], prompt: 'remark', danger: true }],
    allowCreate: true, allowEdit: true, allowDelete: true, modalWidth: '80%',
    autoNumberPrefix: 'WW', autoNumberLabel: '委外单号',
  },
  'outsourcing.issues': {
    title: '委外发料', endpoint: '/api/outsourcing/issues', menuCode: 'outsourcing.issues',
    columns: [...docColumns, { key: 'outsourcing_order_id', title: '委外单', lookup: 'outsourcingOrders' }, { key: 'warehouse_id', title: '来源仓', lookup: 'warehouses' }],
    // 单号可留空：后端按 WWFL+日期+流水生成。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      lookup('outsourcing_order_id', '委外单', 'outsourcingOrders'), lookup('warehouse_id', '来源仓', 'warehouses'), remark],
    lines: [{ name: 'lines', label: '发料明细', fields: linkedLine('outsourcing_material_line_id', '委外物料', 'outsourcing_order_id', '/api/outsourcing/orders', 'materials',
      // 只读：物料由所选的委外物料行决定，显示名称（编码见来源行列）。
      [{ name: 'item_label', label: '物料', kind: 'item', itemSource: 'item_id' }]) }],
    actions: postActions, allowCreate: true, allowEdit: true, allowDelete: true, modalWidth: '80%',
    autoNumberPrefix: 'WWFL', autoNumberLabel: '发料单号',
  },
  'outsourcing.receipts': {
    title: '委外入库', endpoint: '/api/outsourcing/receipts', menuCode: 'outsourcing.receipts',
    columns: [...docColumns, { key: 'outsourcing_order_id', title: '委外单', lookup: 'outsourcingOrders' }, { key: 'warehouse_id', title: '入库仓', lookup: 'warehouses' }],
    // 单号可留空：后端按 WWRK+日期+流水生成。
    fields: [{ ...text('document_no', '单号', false), placeholder: '留空自动生成' }, date(),
      lookup('outsourcing_order_id', '委外单', 'outsourcingOrders'), lookup('warehouse_id', '入库仓', 'warehouses'), remark],
    lines: [{ name: 'lines', label: '入库明细', fields: linkedLine('outsourcing_output_line_id', '委外产出', 'outsourcing_order_id', '/api/outsourcing/orders', 'outputs',
      // 只读：物料由所选的委外产出决定，显示名称（编码见来源行列）。
      [{ name: 'item_label', label: '物料', kind: 'item', itemSource: 'item_id' }]) }],
    actions: postActions, allowCreate: true, allowEdit: true, allowDelete: true, modalWidth: '80%',
    autoNumberPrefix: 'WWRK', autoNumberLabel: '入库单号',
  },
};
