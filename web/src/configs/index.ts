/** 全部页面配置：按模块汇总后交给 ResourcePage 渲染。 */
import type { ResourceConfig } from '../components/resource';
import { masterdataResources } from './masterdata';
import { salesResources } from './sales';
import { purchaseResources } from './purchase';
import { inventoryResources } from './inventory';
import { productionResources } from './production';
import { outsourcingResources } from './outsourcing';
import { systemResources } from './system';
import { reconciliationResources } from './reconciliation';

export const resources: Record<string, ResourceConfig> = {
  ...masterdataResources,
  ...salesResources,
  ...purchaseResources,
  ...inventoryResources,
  ...productionResources,
  ...outsourcingResources,
  ...systemResources,
  ...reconciliationResources,
};

for (const config of Object.values(resources)) {
  config.serverPaging = ['/api/sales/', '/api/purchase/', '/api/production/',
    '/api/outsourcing/', '/api/inventory/', '/api/reconciliation/']
    .some((prefix) => config.endpoint.startsWith(prefix));
}
