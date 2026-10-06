import { get, type Row } from '../../api/client';
import type { Lookup } from './types';

const lookupPaths: Record<Lookup, string> = {
  items: '/api/items', units: '/api/units', warehouses: '/api/warehouses', parties: '/api/parties',
  categories: '/api/item-categories', roles: '/api/system/roles', departments: '/api/system/departments', menus: '/api/system/menus',
  salesOrders: '/api/sales/orders', purchaseOrders: '/api/purchase/orders',
  productionPlans: '/api/production/plans', productionOrders: '/api/production/orders',
  outsourcingOrders: '/api/outsourcing/orders', salesShipments: '/api/sales/shipments',
  salesReturns: '/api/sales/returns', purchaseReceipts: '/api/purchase/receipts',
  productionIssues: '/api/production/issues', outsourcingIssues: '/api/outsourcing/issues',
};
const pagedLookups = new Set<Lookup>([
  'salesOrders', 'purchaseOrders', 'productionPlans', 'productionOrders', 'outsourcingOrders',
  'salesShipments', 'salesReturns', 'purchaseReceipts', 'productionIssues', 'outsourcingIssues',
]);
export async function lookupRows(key: Lookup): Promise<Row[]> {
  const path = lookupPaths[key];
  if (!pagedLookups.has(key)) return get<Row[]>(path);
  const result: Row[] = [];
  for (let offset = 0; ; offset += 500) {
    const page = await get<Row[]>(path, { limit: 500, offset });
    result.push(...page);
    if (page.length < 500) return result;
  }
}
