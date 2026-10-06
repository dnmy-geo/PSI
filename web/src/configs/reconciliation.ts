/** reconciliation 模块的页面配置。 */
import type { ResourceConfig } from '../components/resource';
import { number, lookup, remark, docColumns, docFields } from './factories';

export const reconciliationResources: Record<string, ResourceConfig> = {
  'reconciliation.receipts': {
    title: '收款记录', endpoint: '/api/reconciliation/cash-records', menuCode: 'reconciliation.receipts',
    listParams: { account_type: 'customer' },
    columns: [...docColumns.slice(0, 2), { key: 'party_id', title: '客户', lookup: 'parties' }, { key: 'amount', title: '收款金额' }],
    fields: [...docFields, { ...lookup('party_id', '客户', 'parties'), partyType: 'customer' }, number('amount', '收款金额'),
      lookup('source_id', '关联销售订单（可选）', 'salesOrders', false), remark],
    createTransform: (values) => ({ ...values, account_type: 'customer', record_type: 'receipt', source_type: values.source_id ? 'sales_order' : null }),
    editTransform: (values, original) => ({ ...values, account_type: original.account_type, record_type: 'receipt', source_type: values.source_id ? 'sales_order' : null }),
    allowCreate: true, allowEdit: true, allowDelete: true,
  },
  'reconciliation.supplier_payments': {
    title: '供应商付款', endpoint: '/api/reconciliation/cash-records', menuCode: 'reconciliation.payments',
    listParams: { account_type: 'supplier' },
    columns: [...docColumns.slice(0, 2), { key: 'party_id', title: '供应商', lookup: 'parties' }, { key: 'amount', title: '付款金额' }],
    fields: [...docFields, { ...lookup('party_id', '供应商', 'parties'), partyType: 'supplier' }, number('amount', '付款金额'),
      lookup('source_id', '关联采购订单（可选）', 'purchaseOrders', false), remark],
    createTransform: (values) => ({ ...values, account_type: 'supplier', record_type: 'payment', source_type: values.source_id ? 'purchase_order' : null }),
    editTransform: (values, original) => ({ ...values, account_type: original.account_type, record_type: 'payment', source_type: values.source_id ? 'purchase_order' : null }),
    allowCreate: true, allowEdit: true, allowDelete: true,
  },
  'reconciliation.processor_payments': {
    title: '加工商付款', endpoint: '/api/reconciliation/cash-records', menuCode: 'reconciliation.payments',
    listParams: { account_type: 'processor' },
    columns: [...docColumns.slice(0, 2), { key: 'party_id', title: '加工商', lookup: 'parties' }, { key: 'amount', title: '付款金额' }],
    fields: [...docFields, { ...lookup('party_id', '加工商', 'parties'), partyType: 'processor' }, number('amount', '付款金额'),
      lookup('source_id', '关联委外单（可选）', 'outsourcingOrders', false), remark],
    createTransform: (values) => ({ ...values, account_type: 'processor', record_type: 'payment', source_type: values.source_id ? 'outsourcing_order' : null }),
    editTransform: (values, original) => ({ ...values, account_type: original.account_type, record_type: 'payment', source_type: values.source_id ? 'outsourcing_order' : null }),
    allowCreate: true, allowEdit: true, allowDelete: true,
  },
};
