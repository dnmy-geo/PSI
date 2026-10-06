import { useState } from 'react';
import { Button, Card, Descriptions, Modal, Table, Tabs } from 'antd';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { get, type Row } from '../../api/client';
import { ListFilterBar, type FilterValues } from '../../components/ListFilterBar';
import { getAllPages, matchesKeyword } from '../../utils/listFilters';

const accountLabels = { customer: '客户', supplier: '供应商', processor: '加工商' };
type Account = keyof typeof accountLabels;

export function StatementPage({ account }: { account?: Account }) {
  const [month, setMonth] = useState(dayjs().format('YYYY-MM'));
  const [filters, setFilters] = useState<FilterValues>({});
  const [active, setActive] = useState<Account>(account ?? 'customer');
  const [statement, setStatement] = useState<Row | null>(null);
  const selected = account ?? active;
  const query = useQuery({ queryKey: ['month-end', month, selected],
    queryFn: () => getAllPages('/api/reconciliation/month-end', { month, account_type: selected }) });
  const content = <PageContainer title={`${accountLabels[selected]}对账`}>
    <ListFilterBar fields={[{ key: 'month', label: '对账月份', kind: 'month' }, { key: 'keyword', label: '往来单位' }]}
      initialValues={{ month: dayjs().format('YYYY-MM') }} onApply={(values) => { setMonth(values.month || dayjs().format('YYYY-MM')); setFilters(values); }} />
    <ProTable<Row> rowKey="party_id" search={false}
      dataSource={(query.data ?? []).filter((row) => matchesKeyword(row, filters.keyword ?? '', ['party_code', 'party_name']))} loading={query.isPending}
      pagination={{ pageSize: 20 }} columns={[
        { title: '编码', dataIndex: 'party_code' }, { title: '往来单位', dataIndex: 'party_name' },
        { title: '期初余额', dataIndex: 'opening_balance' }, { title: '本期业务额', dataIndex: 'business_amount' },
        { title: selected === 'customer' ? '本期收款' : '本期付款', dataIndex: 'cash_amount' },
        { title: '期末余额', dataIndex: 'closing_balance' },
        { title: '明细', valueType: 'option', render: (_, row) => <Button type="link" onClick={async () => {
          try { setStatement(await get<Row>(`/api/reconciliation/${selected}/parties/${row.party_id}/statement`, { month })); }
          catch { setStatement(null); }
        }}>查看</Button> },
      ]} />
    <Modal title="对账明细" className="psi-editor-modal" width="80%" open={!!statement}
      onCancel={() => setStatement(null)} destroyOnHidden
      footer={<Button onClick={() => setStatement(null)}>关闭</Button>}>
      {statement && <div className="page-stack">
        <Descriptions bordered size="small" items={[
          { key: 'party', label: '往来单位', children: String(statement.party_name) },
          { key: 'opening', label: '期初余额', children: String(statement.opening_balance) },
          { key: 'business', label: '业务额', children: String(statement.business_amount) },
          { key: 'cash', label: '收付款', children: String(statement.cash_amount) },
          { key: 'closing', label: '期末余额', children: String(statement.closing_balance) },
        ]} />
        <Card title="业务流水" size="small"><Table rowKey="id" dataSource={statement.business_lines as Row[]} size="small" pagination={false}
          columns={[{ title: '发生时间', dataIndex: 'posted_at' }, { title: '来源', dataIndex: 'source_type' }, { title: '金额变动', dataIndex: 'amount_delta' }]} /></Card>
        <Card title="收付款记录" size="small"><Table rowKey="id" dataSource={statement.cash_lines as Row[]} size="small" pagination={false}
          columns={[{ title: '单号', dataIndex: 'document_no' }, { title: '日期', dataIndex: 'document_date' }, { title: '金额', dataIndex: 'amount' }]} /></Card>
      </div>}
    </Modal>
  </PageContainer>;
  if (account) return content;
  return <Tabs activeKey={active} onChange={(value) => setActive(value as Account)}
    items={(Object.keys(accountLabels) as Account[]).map((kind) => ({ key: kind, label: `${accountLabels[kind]}对账`, children: kind === active ? content : null }))} />;
}

