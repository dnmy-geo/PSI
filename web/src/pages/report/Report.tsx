import { useState } from 'react';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import { get, type Row } from '../../api/client';
import { ListFilterBar, type FilterValues } from '../../components/ListFilterBar';
import { matchesKeyword } from '../../utils/listFilters';

const metricLabels: Record<string, string> = {
  ordered_base: '订单数量', shipped_base: '出库数量', returned_base: '退货数量',
  unshipped_base: '截至期末未发数量', unreceived_base: '截至期末未入库数量',
  replacement_base: '补发数量', received_base: '入库数量', planned_base: '计划数量',
  issued_base: '领料数量', consumed_base: '实际消耗', produced_base: '生产入库',
  output_expected_base: '预计产出', self_material_expected_base: '预计我方供料',
};

export function Report({ kind, title }: { kind: string; title: string }) {
  const [period, setPeriod] = useState<[Dayjs, Dayjs]>([dayjs().startOf('month'), dayjs()]);
  const [filters, setFilters] = useState<FilterValues>({});
  const initialFilters = { dateFrom: dayjs().startOf('month').format('YYYY-MM-DD'), dateTo: dayjs().format('YYYY-MM-DD') };
  const query = useQuery({ queryKey: ['report', kind, period[0].format('YYYY-MM-DD'), period[1].format('YYYY-MM-DD')],
    queryFn: () => get<Row[]>(`/api/reports/${kind}`, { date_from: period[0].format('YYYY-MM-DD'), date_to: period[1].format('YYYY-MM-DD') }) });
  const metrics = Array.from(new Set((query.data ?? []).flatMap((row) => Object.keys((row.quantities ?? {}) as Row))));
  const rows = (query.data ?? []).filter((row) => matchesKeyword(row, filters.keyword ?? ''));
  return <PageContainer title={title}>
    <ListFilterBar fields={[{ key: 'date', label: '统计期间', kind: 'dateRange' }, { key: 'keyword', label: '关键词' }]}
      initialValues={initialFilters} onApply={(values) => {
        setFilters(values);
        setPeriod(values.dateFrom && values.dateTo ? [dayjs(values.dateFrom), dayjs(values.dateTo)] : [dayjs().startOf('month'), dayjs()]);
      }} />
    <ProTable<Row> rowKey={(row) => `${row.warehouse_id ?? ''}:${row.item_id}`} search={false} pagination={{ pageSize: 20 }}
      dataSource={rows} loading={query.isPending} scroll={{ x: 'max-content' }}
      columns={kind === 'inventory' ? [
        { title: '仓库', dataIndex: 'warehouse_code' }, { title: '物料编码', dataIndex: 'item_code' },
        { title: '物料名称', dataIndex: 'item_name' }, { title: '基本单位', dataIndex: 'base_unit_code' },
        { title: '期间入库', dataIndex: 'period_in_base' }, { title: '期间出库', dataIndex: 'period_out_base' },
        { title: '期间净变动', dataIndex: 'period_net_base' }, { title: '当前结存', dataIndex: 'current_balance_base' },
        { title: '期间盘点差异', dataIndex: 'stocktake_difference_base' },
      ] : [
        { title: '物料编码', dataIndex: 'item_code' }, { title: '物料名称', dataIndex: 'item_name' },
        { title: '基本单位', dataIndex: 'base_unit_code' },
        ...metrics.map((metric) => ({ title: metricLabels[metric] ?? metric, dataIndex: ['quantities', metric] })),
        { title: '业务金额', dataIndex: 'business_amount' },
      ]} />
  </PageContainer>;
}

