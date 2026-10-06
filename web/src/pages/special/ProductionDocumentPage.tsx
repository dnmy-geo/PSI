import { Alert, Button } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { get, type Row } from '../../api/client';
import { resources } from '../../configs';
import { ResourcePage, type ResourceConfig } from '../../components/resource';

export function ProductionDocumentPage({ kind }: { kind: 'issues' | 'consumptions' | 'receipts' }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const orderId = searchParams.get('order_id');
  const focusedOrder = useQuery({ queryKey: ['production-order-focus', orderId],
    queryFn: () => get<Row>(`/api/production/orders/${orderId}`), enabled: !!orderId });
  const documentConfig: ResourceConfig = { ...resources[`production.${kind}`],
    ...(orderId ? { listParams: { production_order_id: orderId }, initialValues: { production_order_id: orderId } } : {}),
  };
  return <>
    {orderId && <Alert type="info" showIcon style={{ marginBottom: 12 }}
      message={`当前生产订单：${String(focusedOrder.data?.document_no ?? orderId)}`}
      action={<Button size="small" onClick={() => {
        const next = new URLSearchParams(searchParams); next.delete('order_id'); setSearchParams(next, { replace: true });
      }}>查看全部订单</Button>} />}
    <ResourcePage key={`${kind}-${orderId}`} config={documentConfig} />
  </>;
}

