import { useState } from 'react';
import { Alert, App as AntApp, Button, Card, DatePicker, Descriptions, Modal, Space, Table, Tabs, Upload } from 'antd';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { useNavigate } from 'react-router-dom';
import { get, upload, type Row } from '../../api/client';
import { resources } from '../../configs';
import { ResourcePage } from '../../components/resource';

const carryoverKinds = [
  { key: 'sales', label: '销售未发' }, { key: 'purchase', label: '采购未入' },
  { key: 'production', label: '生产未完' }, { key: 'outsourcing', label: '委外未完' },
] as const;

function CarryoverImport({ kind }: { kind: typeof carryoverKinds[number]['key'] }) {
  const { message } = AntApp.useApp();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Row[]>([]);
  const [version, setVersion] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const documents = useQuery({ queryKey: ['carryover-documents', kind, version],
    queryFn: () => get<Row[]>('/api/system/carryover/documents', { kind }) });
  const selected = useQuery({ queryKey: ['carryover-document', selectedId],
    queryFn: () => get<Row>(`/api/system/carryover/documents/${selectedId}`), enabled: !!selectedId });
  const fileData = () => { const data = new FormData(); if (file) data.set('file', file); return data; };
  return <div className="page-stack">
    <Alert type="info" showIcon message="仅导入剩余待履约数量"
      description="原数量和已完成数量用于追溯；历史库存、往来金额分别由期初库存和期初往来余额承接。接续单据导入为草稿，仍需按正常权限完成审批或启用后再办理业务。" />
    <Card title="接续业务 Excel 导入" extra={<a href={`/api/system/carryover/template/${kind}`}>下载模板</a>}>
      <Space wrap>
        <Upload key={version} beforeUpload={(selected) => { setFile(selected); setPreview([]); return false; }}
          maxCount={1} onRemove={() => { setFile(null); setPreview([]); }}>
          <Button>选择 Excel 文件</Button>
        </Upload>
        <Button disabled={!file} onClick={async () => {
          try { setPreview(await upload<Row[]>(`/api/system/carryover/preview/${kind}`, fileData())); }
          catch (error) { setPreview([]); message.error((error as Error).message); }
        }}>预览并校验</Button>
        <Button type="primary" disabled={!file || !preview.length} onClick={async () => {
          try {
            const result = await upload<{ imported_documents: number }>(`/api/system/carryover/import/${kind}`, fileData());
            message.success(`已导入 ${result.imported_documents} 张接续单据`);
            setFile(null); setPreview([]); setVersion((value) => value + 1);
          } catch (error) { message.error((error as Error).message); }
        }}>确认导入草稿</Button>
      </Space>
      {preview.length > 0 && <Table<Row> style={{ marginTop: 16 }} rowKey="original_document_no"
        size="small" pagination={{ pageSize: 10 }} dataSource={preview} columns={[
          { title: '原单号', dataIndex: 'original_document_no' }, { title: '接续单号', dataIndex: 'document_no' },
          { title: '启用日期', dataIndex: 'effective_date' }, { title: '往来单位编码', dataIndex: 'party_code' },
          { title: '原单行数', dataIndex: 'line_count' }, { title: '剩余行数', dataIndex: 'remaining_lines' },
        ]} />}
    </Card>
    <Card title="已导入的接续业务">
      <Table<Row> rowKey="id" loading={documents.isPending} dataSource={documents.data ?? []}
        pagination={{ pageSize: 10 }} columns={[
          { title: '原单号', dataIndex: 'original_document_no' }, { title: '接续单号', dataIndex: 'document_no' },
          { title: '启用日期', dataIndex: 'effective_date' }, { title: '行数', dataIndex: 'line_count' },
          { title: '剩余基本单位合计', dataIndex: 'remaining_quantity_base' },
          { title: '操作', render: (_, row) => <Space size={0}>
            <Button type="link" onClick={() => setSelectedId(String(row.id))}>查看明细</Button>
            <Button type="link" onClick={() => navigate({
              sales: '/sales/orders', purchase: '/purchase/orders',
              production: '/production/orders', outsourcing: '/outsourcing/orders',
            }[kind])}>打开业务列表</Button>
          </Space> },
        ]} />
    </Card>
    <Modal title="接续业务明细" className="psi-editor-modal" width="80%" open={!!selectedId}
      onCancel={() => setSelectedId(null)} destroyOnHidden
      footer={<Button onClick={() => setSelectedId(null)}>关闭</Button>}>
      {selected.data && <div className="page-stack">
        <Descriptions bordered size="small" items={[
          { key: 'original', label: '原单号', children: String(selected.data.original_document_no) },
          { key: 'continuation', label: '接续单号', children: String(selected.data.document_no) },
          { key: 'date', label: '启用日期', children: String(selected.data.effective_date) },
        ]} />
        <Table<Row> rowKey="source_row_no" size="small" pagination={false}
          dataSource={(selected.data.lines as Row[]) ?? []} columns={[
            { title: '物料', dataIndex: 'item_code' }, { title: '原数量', dataIndex: 'original_quantity_base' },
            { title: '已完成', dataIndex: 'completed_quantity_base' },
            { title: '剩余', dataIndex: 'remaining_quantity_base' },
            { title: '历史来源单', dataIndex: 'historical_source_no' },
            { title: '操作', render: (_, row) => row.historical_source_id && (kind === 'sales' || kind === 'purchase')
              ? <Button type="link" onClick={() => navigate(kind === 'sales'
                ? `/sales/returns?original_shipment_id=${row.historical_source_id}`
                : `/purchase/returns?original_receipt_id=${row.historical_source_id}`)}>以此来源办理退货</Button> : null },
          ]} />
      </div>}
    </Modal>
  </div>;
}

export function InitializationPage() {
  const { message } = AntApp.useApp();
  const [file, setFile] = useState<File | null>(null);
  const [stockPreview, setStockPreview] = useState<Row[]>([]);
  const [date, setDate] = useState(dayjs());
  const [version, setVersion] = useState(0);
  const [accountFile, setAccountFile] = useState<File | null>(null);
  const [accountPreview, setAccountPreview] = useState<Row[]>([]);
  const [accountVersion, setAccountVersion] = useState(0);
  const stockConfig = {
    title: '期初库存单', endpoint: '/api/inventory/opening-stock', menuCode: 'system.initialization',
    columns: [
      { key: 'document_no', title: '单号' }, { key: 'effective_date', title: '生效日期' },
      { key: 'status', title: '状态' },
    ],
    actions: [
      { key: 'post', label: '确认入账', statuses: ['draft'] },
      { key: 'reverse', label: '冲销', statuses: ['posted'], prompt: 'reason' as const, danger: true },
    ],
  };
  return <Tabs items={[
    { key: 'stock', label: '期初库存', children: <div className="page-stack">
      <Card title="Excel 导入" extra={<a href="/api/inventory/opening-stock/template">下载模板</a>}>
        <Space wrap>
          <DatePicker value={date} onChange={(value) => value && setDate(value)} />
          <Upload key={version} beforeUpload={(selected) => { setFile(selected); setStockPreview([]); return false; }}
            maxCount={1} onRemove={() => { setFile(null); setStockPreview([]); }}><Button>选择 Excel 文件</Button></Upload>
          <Button disabled={!file} onClick={async () => {
            if (!file) return;
            const data = new FormData(); data.set('file', file);
            try { setStockPreview(await upload<Row[]>('/api/inventory/opening-stock/preview', data)); }
            catch (error) { setStockPreview([]); message.error((error as Error).message); }
          }}>预览并校验</Button>
          <Button type="primary" disabled={!file || !stockPreview.length} onClick={async () => {
            if (!file) return;
            const data = new FormData(); data.set('effective_date', date.format('YYYY-MM-DD')); data.set('file', file);
            try { await upload('/api/inventory/opening-stock/import', data); message.success('导入草稿成功，请核对后确认入账'); setFile(null); setStockPreview([]); setVersion((value) => value + 1); }
            catch (error) { message.error((error as Error).message); }
          }}>导入草稿</Button>
        </Space>
        {stockPreview.length > 0 && <Table<Row> style={{ marginTop: 16 }} rowKey="row_no" size="small"
          pagination={{ pageSize: 10 }} dataSource={stockPreview} columns={[
            { title: '行号', dataIndex: 'row_no' }, { title: '仓库编码', dataIndex: 'warehouse_code' },
            { title: '物料编码', dataIndex: 'item_code' }, { title: '单位编码', dataIndex: 'unit_code' },
            { title: '输入数量', dataIndex: 'quantity' }, { title: '换算系数', dataIndex: 'factor' },
            { title: '基本单位数量', dataIndex: 'quantity_base' },
          ]} />}
      </Card>
      <ResourcePage key={version} config={stockConfig} />
    </div> },
    { key: 'accounts', label: '期初往来余额', children: <div className="page-stack">
      <Card title="Excel 导入" extra={<a href="/api/reconciliation/opening-balances/template">下载模板</a>}>
        <Space wrap>
          <Upload key={accountVersion} beforeUpload={(selected) => { setAccountFile(selected); setAccountPreview([]); return false; }}
            maxCount={1} onRemove={() => { setAccountFile(null); setAccountPreview([]); }}>
            <Button>选择 Excel 文件</Button>
          </Upload>
          <Button disabled={!accountFile} onClick={async () => {
            if (!accountFile) return;
            const data = new FormData(); data.set('file', accountFile);
            try { setAccountPreview(await upload<Row[]>('/api/reconciliation/opening-balances/preview', data)); }
            catch (error) { setAccountPreview([]); message.error((error as Error).message); }
          }}>预览并校验</Button>
          <Button type="primary" disabled={!accountFile || !accountPreview.length} onClick={async () => {
            if (!accountFile) return;
            const data = new FormData(); data.set('file', accountFile);
            try {
              const result = await upload<{ imported: number }>('/api/reconciliation/opening-balances/import', data);
              message.success(`已导入 ${result.imported} 条期初余额`);
              setAccountFile(null); setAccountPreview([]); setAccountVersion((value) => value + 1);
            } catch (error) { message.error((error as Error).message); }
          }}>确认导入</Button>
        </Space>
        {accountPreview.length > 0 && <Table<Row> style={{ marginTop: 16 }} rowKey="row_no" size="small"
          pagination={{ pageSize: 10 }} dataSource={accountPreview} columns={[
            { title: '行号', dataIndex: 'row_no' }, { title: '往来单位编码', dataIndex: 'party_code' },
            { title: '往来单位', dataIndex: 'party_name' }, { title: '账户类型', dataIndex: 'account_type' },
            { title: '启用日期', dataIndex: 'effective_date' }, { title: '期初金额', dataIndex: 'amount' },
          ]} />}
      </Card>
      <ResourcePage key={accountVersion} config={resources['system.opening_balances']} />
    </div> },
    { key: 'carryover', label: '未完成业务接续', children: <Tabs items={carryoverKinds.map(({ key, label }) => ({
      key, label, children: <CarryoverImport kind={key} />,
    }))} /> },
  ]} />;
}

