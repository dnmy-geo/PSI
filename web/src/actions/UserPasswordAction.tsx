import { useState } from 'react';
import { App as AntApp, Button, Input, Modal } from 'antd';
import { post, type Row } from '../api/client';

export function UserPasswordAction({ row }: { row: Row }) {
  const { message } = AntApp.useApp();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  return <><Button type="link" size="small" onClick={() => setOpen(true)}>重设密码</Button>
    <Modal title={`重设 ${row.username} 的密码`} open={open} okText="重设" onCancel={() => { setOpen(false); setPassword(''); }}
      onOk={async () => {
        if (password.length < 6) { message.warning('密码至少 6 位'); return; }
        try { await post(`/api/system/users/${row.id}/reset-password`, { password }); message.success('密码已重设，该用户现有会话已撤销'); setOpen(false); setPassword(''); }
        catch (error) { message.error((error as Error).message); }
      }}>
      <Input.Password autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="至少 6 位新密码" />
    </Modal>
  </>;
}

