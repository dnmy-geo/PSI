import { Tabs } from 'antd';
import { resources } from '../../configs';
import { ResourcePage } from '../../components/resource';

export function PaymentsPage() {
  return <Tabs items={[
    { key: 'supplier', label: '供应商付款', children: <ResourcePage config={resources['reconciliation.supplier_payments']} /> },
    { key: 'processor', label: '加工商付款', children: <ResourcePage config={resources['reconciliation.processor_payments']} /> },
  ]} />;
}

