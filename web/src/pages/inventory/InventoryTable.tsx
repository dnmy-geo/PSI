import { useState } from 'react';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { get, getPage, type Row } from '../../api/client';
import { ListFilterBar, type FilterValues } from '../../components/ListFilterBar';
import { getAllPages, matchesDateRange, matchesKeyword } from '../../utils/listFilters';

/**
 * 库存流水的业务类型。值是后端 `movement_kind`，规则为「业务_方向」，
 * 冲销流水是「业务_reverse_in/out」。没收录的类型直接显示原值，便于发现新类型。
 */
const movementKindLabels: Record<string, string> = {
  in: '期初入库', opening_reverse_out: '期初冲销',
  manual_adjustment: '库存调整', adjustment_reversal: '调整冲销', stocktake_difference: '盘点差异',
  transfer_out: '调拨出库', transfer_in: '调拨入库',
  transfer_reverse_in: '调拨冲销', transfer_reverse_out: '调拨冲销',
  purchase_in: '采购入库', purchase_receipt_reverse_out: '采购入库冲销',
  purchase_return_out: '采购退货', purchase_return_reverse_in: '采购退货冲销',
  sales_out: '销售出库', sales_shipment_reverse_in: '销售出库冲销',
  sales_return_in: '销售退货', sales_return_reverse_out: '销售退货冲销',
  production_issue_out: '生产领料', production_issue_in: '生产领料（现场仓）',
  production_issue_reverse_in: '生产领料冲销', production_issue_reverse_out: '生产领料冲销',
  production_consumption_out: '生产消耗', production_consumption_reverse_in: '生产消耗冲销',
  production_receipt_in: '生产入库', production_receipt_reverse_out: '生产入库冲销',
  outsourcing_issue_out: '委外发料', outsourcing_issue_reverse: '委外发料冲销',
  outsourcing_receipt_in: '委外入库', outsourcing_receipt_reverse: '委外入库冲销',
};
const movementKind = (value: unknown) => movementKindLabels[String(value ?? '')] ?? String(value ?? '—');

export function InventoryTable({ kind }: { kind: 'balances' | 'movements' }) {
  const path = `/api/inventory/${kind}`;
  const [filters, setFilters] = useState<FilterValues>({});
  const items = useQuery({ queryKey: ['inventory-items'], queryFn: () => get<Row[]>('/api/items'), retry: false });
  const warehouses = useQuery({ queryKey: ['inventory-warehouses'], queryFn: () => get<Row[]>('/api/warehouses'), retry: false });
  const findItem = (value: unknown) => items.data?.find((row) => row.id === value);
  const itemCode = (value: unknown) => {
    const item = findItem(value);
    return item ? String(item.code) : String(value ?? '—');
  };
  const itemLabel = (value: unknown) => {
    const item = findItem(value);
    return item ? String(item.name ?? item.code) : String(value ?? '—');
  };
  // 筛选仍按「编码 · 名称」整体匹配。
  const itemName = (value: unknown) => {
    const item = findItem(value);
    return item ? `${item.code} · ${item.name}` : String(value ?? '—');
  };
  const warehouseName = (value: unknown) => {
    const warehouse = warehouses.data?.find((row) => row.id === value);
    return warehouse ? `${warehouse.code} · ${warehouse.name}` : String(value ?? '—');
  };
  return <PageContainer title={kind === 'balances' ? '库存查询' : '库存流水'}>
    <ListFilterBar fields={[{ key: 'keyword', label: '仓库或物料' }, ...(kind === 'movements' ? [{ key: 'date', label: '过账时间', kind: 'dateRange' as const }] : [])]} onApply={setFilters} />
    <ProTable<Row> key={JSON.stringify(filters)} rowKey={kind === 'balances' ? (row) => `${row.warehouse_id}:${row.item_id}` : 'id'}
    search={false} pagination={{ pageSize: 20 }} scroll={{ x: 'max-content' }}
    request={async (params) => {
      const page = params.current ?? 1; const size = params.pageSize ?? 20;
      const matches = (row: Row) => matchesKeyword({ warehouse: warehouseName(row.warehouse_id), item: itemName(row.item_id), ...row }, filters.keyword ?? '') &&
        (kind === 'balances' || matchesDateRange(row.posted_at, filters.dateFrom, filters.dateTo));
      if (kind === 'balances') return { data: (await get<Row[]>(path)).filter(matches), success: true };
      if (Object.values(filters).some(Boolean)) {
        const rows = (await getAllPages(path)).filter(matches);
        return { data: rows.slice((page - 1) * size, page * size), success: true, total: rows.length };
      }
      const { data, total } = await getPage<Row[]>(path, { limit: size, offset: (page - 1) * size });
      return { data, success: true, total };
    }}
    columns={kind === 'balances' ? [
      // 五列等宽：不给宽度的话，仓库和物料名称会把留白全吃掉，
      // 结存数量、基本单位被挤成窄条（与计量单位列表同一种均分做法）。
      { title: '仓库', dataIndex: 'warehouse_id', width: 200, render: (_, row) => warehouseName(row.warehouse_id) },
      { title: '物料编码', dataIndex: 'item_id', width: 200, render: (_, row) => itemCode(row.item_id) },
      { title: '物料名称', dataIndex: 'item_id', width: 200, render: (_, row) => itemLabel(row.item_id) },
      // 结存数量固定 3 位小数；单位单独一列跟在后面。
      { title: '结存数量', dataIndex: 'quantity_base', width: 200, render: (_, row) => Number(row.quantity_base).toFixed(3) },
      { title: '基本单位', dataIndex: 'base_unit_code', width: 200 },
    ] : [
      // 七列等宽均分（与库存查询一致）：只给部分列宽度的话，仓库和物料名称会把留白全吃掉。
      // 接口给的是 ISO 时间串，过账时间统一显示到秒（与单据列表的创建/修改时间一致）。
      { title: '过账时间', dataIndex: 'posted_at', width: 180,
        render: (_, row) => row.posted_at ? dayjs(String(row.posted_at)).format('YYYY-MM-DD HH:mm:ss') : '—' },
      { title: '仓库', dataIndex: 'warehouse_id', width: 180, render: (_, row) => warehouseName(row.warehouse_id) },
      { title: '物料编码', dataIndex: 'item_id', width: 180, render: (_, row) => itemCode(row.item_id) },
      { title: '物料名称', dataIndex: 'item_id', width: 180, render: (_, row) => itemLabel(row.item_id) },
      { title: '变动数量', dataIndex: 'quantity_delta_base', width: 180 },
      { title: '类型', dataIndex: 'movement_kind', width: 180, render: (_, row) => movementKind(row.movement_kind) },
      // 来源单据显示单号（后端按来源类型翻译），不再裸露 UUID。
      { title: '来源单据', dataIndex: 'source_document_no', width: 180,
        render: (_, row) => row.source_document_no ? String(row.source_document_no) : '—' },
    ]} />
  </PageContainer>;
}

