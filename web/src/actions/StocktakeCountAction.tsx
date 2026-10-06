import { useState } from 'react';
import { App as AntApp, Button, Form, InputNumber, Modal, Select } from 'antd';
import { get, put, type Row } from '../api/client';

export function StocktakeCountAction({ row, refresh, canUpdate }: { row: Row; refresh: () => void; canUpdate: boolean }) {
  const { message } = AntApp.useApp();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [items, setItems] = useState<Row[]>([]);
  if (row.status !== 'counting' || !canUpdate) return null;
  return <><Button type="link" size="small" onClick={async () => {
    try {
      const [doc, itemRows] = await Promise.all([get<Row>(`/api/inventory/stocktakes/${row.id}`), get<Row[]>('/api/items')]);
      setItems(itemRows);
      form.setFieldsValue({ lines: (doc.lines as Row[]).map((line) => ({ item_id: line.item_id, counted_quantity_base: line.counted_quantity_base })) });
      setOpen(true);
    } catch (error) { message.error((error as Error).message); }
  }}>录入实盘数</Button>
    <Modal title="录入实盘数" className="psi-editor-modal psi-split-modal" open={open} width={700} onCancel={() => setOpen(false)} onOk={async () => {
      try { const values = await form.validateFields(); await put(`/api/inventory/stocktakes/${row.id}/counts`, values);
        message.success('实盘数已保存'); setOpen(false); refresh(); }
      catch (error) { message.error((error as Error).message); }
    }}>
      <div className="psi-editor-intro"><span className="psi-editor-kicker">STOCKTAKE</span><p>逐项录入实际清点数量，保存后再提交盘点审批。</p></div>
      <Form form={form} layout="vertical"><Form.List name="lines">{(fields, { add, remove }) => <div className="psi-split-orders">
        {fields.map((field, index) => <div className="psi-split-output psi-count-line" key={field.key}>
          <span className="psi-count-index">{String(index + 1).padStart(2, '0')}</span>
          <Form.Item label="物料" name={[field.name, 'item_id']} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" placeholder="选择物料" options={items.map((item) => ({ label: `${item.code} · ${item.name}`, value: item.id }))} /></Form.Item>
          <Form.Item label="实盘数量" name={[field.name, 'counted_quantity_base']} rules={[{ required: true }]}><InputNumber min={0} precision={6} placeholder="数量" /></Form.Item>
          <Button danger size="small" onClick={() => remove(field.name)}>删除</Button>
        </div>)}
        <Button className="psi-split-add" onClick={() => add()}>添加物料</Button>
      </div>}</Form.List></Form>
    </Modal>
  </>;
}

