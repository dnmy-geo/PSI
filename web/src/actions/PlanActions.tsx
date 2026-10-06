import { useState } from 'react';
import { App as AntApp, Button, Form, Input, InputNumber, Modal, Select, Table } from 'antd';
import { get, post, type Row } from '../api/client';

export function PlanActions({ row, refresh, canPost }: { row: Row; refresh: () => void; canPost: boolean }) {
  const { message } = AntApp.useApp();
  const [shortage, setShortage] = useState<Row[] | null>(null);
  const [autoOpen, setAutoOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [count, setCount] = useState<number>(1);
  const [plan, setPlan] = useState<Row | null>(null);
  const [planItems, setPlanItems] = useState<Row[]>([]);
  const [form] = Form.useForm();
  const showShortage = async () => {
    try { const result = await get<{ lines: Row[] }>(`/api/production/plans/${row.id}/shortage`); setShortage(result.lines); }
    catch (error) { message.error((error as Error).message); }
  };
  const openManual = async () => {
    try {
      const [selectedPlan, items] = await Promise.all([
        get<Row>(`/api/production/plans/${row.id}`), get<Row[]>('/api/items'),
      ]);
      setPlan(selectedPlan); setPlanItems(items); form.resetFields(); setManualOpen(true);
    }
    catch (error) { message.error((error as Error).message); }
  };
  return <>
    <Button type="link" size="small" onClick={showShortage}>多级缺料</Button>
    {row.status === 'open' && canPost && <><Button type="link" size="small" onClick={() => setAutoOpen(true)}>均分拆单</Button>
      <Button type="link" size="small" onClick={openManual}>手动拆单</Button></>}
    <Modal title="多级缺料" className="psi-editor-modal" width="80%" open={shortage !== null}
      onCancel={() => setShortage(null)} destroyOnHidden
      footer={<Button onClick={() => setShortage(null)}>关闭</Button>}>
      <Table rowKey="item_id" size="small" dataSource={shortage ?? []} pagination={false} scroll={{ x: 'max-content' }}
        columns={[{ title: '物料', key: 'item', render: (_, line: Row) => `${line.item_code} · ${line.item_name}` },
          { title: '类型', dataIndex: 'item_type', render: (value: string) => ({ raw_material: '原材料', semi_finished: '半成品', finished: '成品' }[value] ?? value) },
          { title: '需求', dataIndex: 'demand_quantity_base' }, { title: '可用', dataIndex: 'available_quantity_base' },
          { title: '缺量', dataIndex: 'shortage_quantity_base' }]} />
    </Modal>
    <Modal title="按数量均分生产订单" className="psi-editor-modal psi-split-modal" width="80%" open={autoOpen} onCancel={() => setAutoOpen(false)} onOk={async () => {
      try { await post(`/api/production/plans/${row.id}/split/auto`, { order_count: count }); message.success('拆单成功'); setAutoOpen(false); refresh(); }
      catch (error) { message.error((error as Error).message); }
    }}><div className="psi-editor-intro"><span className="psi-editor-kicker">PRODUCTION ORDERS</span><p>按计划剩余数量平均生成指定数量的生产订单。</p></div>
      <div className="psi-editor-section psi-split-count"><label htmlFor="split-order-count">生成订单数量</label>
        <InputNumber id="split-order-count" min={1} max={100} precision={0} value={count} onChange={(value) => setCount(value ?? 1)} addonAfter="张" />
      </div></Modal>
    <Modal title="手动拆分生产订单" className="psi-editor-modal psi-split-modal" width="80%" open={manualOpen} onCancel={() => setManualOpen(false)}
      onOk={async () => { try {
        const values = await form.validateFields();
        await post(`/api/production/plans/${row.id}/split/manual`, values);
        message.success('拆单成功'); setManualOpen(false); refresh();
      } catch (error) { message.error((error as Error).message); } }}>
      <div className="psi-editor-intro"><span className="psi-editor-kicker">PRODUCTION ORDERS</span><p>每张订单选择计划产出项和整数数量，所有订单的合计不得超过计划剩余量。</p></div>
      <Form form={form} layout="vertical" initialValues={{ orders: [{ outputs: [{}] }] }}>
        <Form.List name="orders">{(orders, { add, remove }) => <div className="psi-split-orders">
          {orders.map((order, index) => <section className="psi-editor-section psi-split-order" key={order.key}>
            <div className="psi-editor-section-heading"><span className="psi-editor-step">{String(index + 1).padStart(2, '0')}</span><div><h3>生产订单 {index + 1}</h3><p>填写订单编号与计划产出</p></div><Button danger size="small" onClick={() => remove(order.name)}>移除</Button></div>
            <Form.Item label="订单编号" name={[order.name, 'document_no']}><Input placeholder="留空自动生成" /></Form.Item>
            <Form.List name={[order.name, 'outputs']}>{(outputs, outputActions) => <div className="psi-split-outputs">
              {outputs.map((output) => <div className="psi-split-output" key={output.key}>
                <Form.Item label="计划产出项" name={[output.name, 'production_plan_line_id']} rules={[{ required: true }]}>
                  <Select showSearch optionFilterProp="label" placeholder="选择计划产出" options={((plan?.lines ?? []) as Row[]).map((line) => {
                    const item = planItems.find((entry) => entry.id === line.item_id);
                    return { value: line.id, label: `${item ? `${item.code} · ${item.name}` : line.item_id} · 剩余 ${line.remaining_quantity_base}${line.unit_code ? ` ${String(line.unit_code)}` : ''}` };
                  })} />
                </Form.Item>
                <Form.Item label="计划数量" name={[output.name, 'planned_quantity_base']} rules={[{ required: true }]}><InputNumber min={1} precision={0} placeholder="数量" /></Form.Item>
                <Button danger size="small" onClick={() => outputActions.remove(output.name)}>删除</Button>
              </div>)}
              <Button className="psi-split-add" onClick={() => outputActions.add()}>添加产出项</Button>
            </div>}</Form.List>
          </section>)}
          <Button className="psi-split-add" onClick={() => add({ outputs: [{}] })}>添加生产订单</Button>
        </div>}</Form.List>
      </Form>
    </Modal>
  </>;
}

