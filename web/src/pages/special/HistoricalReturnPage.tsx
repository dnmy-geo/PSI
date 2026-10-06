import { Alert } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { resources } from '../../configs';
import { ResourcePage } from '../../components/resource';

export function HistoricalReturnPage({ kind }: { kind: 'sales' | 'purchase' }) {
  const [searchParams] = useSearchParams();
  const field = kind === 'sales' ? 'original_shipment_id' : 'original_receipt_id';
  const sourceId = searchParams.get(field);
  return <>
    {sourceId && <Alert type="info" showIcon style={{ marginBottom: 12 }}
      message="已选择期初历史来源单，请新建退货单并核对明细与退货仓库" />}
    <ResourcePage key={`${kind}-${sourceId}`} config={{
      ...resources[`${kind}.returns`],
      ...(sourceId ? { initialValues: { [field]: sourceId } } : {}),
    }} />
  </>;
}

