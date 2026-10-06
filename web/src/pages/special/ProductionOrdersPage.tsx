import { Button, Space } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { get } from '../../api/client';
import { resources } from '../../configs';
import { ResourcePage } from '../../components/resource';
import { ProductionCancelAction } from '../../actions/ProductionCancelAction';

export function ProductionOrdersPage() {
  const navigate = useNavigate();
  const permissions = useQuery({ queryKey: ['my-permissions'], queryFn: () => get<Record<string, string[]>>('/api/system/my-permissions') });
  const canView = (code: string) => permissions.data?.[code]?.includes('view');
  return <ResourcePage config={{ ...resources['production.orders'], allowDelete: false,
    customAction: (row, refresh, can) => <Space size={0} wrap>
      {canView('production.issues') && <Button type="link" size="small" onClick={() => navigate(`/production/issues?order_id=${row.id}`)}>领料</Button>}
      {canView('production.consumptions') && <Button type="link" size="small" onClick={() => navigate(`/production/consumptions?order_id=${row.id}`)}>消耗</Button>}
      {canView('production.receipts') && <Button type="link" size="small" onClick={() => navigate(`/production/receipts?order_id=${row.id}`)}>入库</Button>}
      {can('delete') && <ProductionCancelAction row={row} refresh={refresh} />}
    </Space>,
  }} />;
}

