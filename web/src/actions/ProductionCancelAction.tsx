import { Alert, App as AntApp, Button } from 'antd';
import { remove, type Row } from '../api/client';

export function ProductionCancelAction({ row, refresh }: { row: Row; refresh: () => void }) {
  const { message, modal } = AntApp.useApp();
  if (row.status === 'cancelled') return null;
  // 被后端拒绝时关闭旧确认框并带着错误重开：在 onOk 里抛出会让 antd 产生未处理的 promise 拒绝。
  const ask = (failure?: string) => modal.confirm({
    title: '取消生产订单',
    // 与生产管理其它弹窗保持同一宽度。
    width: '80%',
    content: <div className="page-stack">
      {failure && <Alert type="error" showIcon message={failure} />}
      <span>已生效的领料、消耗和入库必须先按相反顺序冲销。</span>
    </div>,
    okButtonProps: { danger: true },
    onOk: async () => {
      try { await remove(`/api/production/orders/${row.id}`); message.success('生产订单已取消'); refresh(); }
      catch (error) { const text = (error as Error).message; message.error(text); ask(text); }
    },
  });
  return <Button type="link" danger size="small" onClick={() => ask()}>取消订单</Button>;
}
