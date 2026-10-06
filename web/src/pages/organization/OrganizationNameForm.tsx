import { useState } from 'react';
import { App as AntApp, Button, Form, Input } from 'antd';
import { CheckCircleFilled, ExclamationCircleFilled } from '@ant-design/icons';
import { put } from '../../api/client';

export type OrganizationNameFormProps = {
  /** 服务端当前已保存的组织名称，既作表单初值，也作「是否有未保存改动」的比较基准。 */
  savedName: string;
  canUpdate: boolean;
  /** 保存成功后的回调，由页面刷新组织信息。 */
  onSaved: () => Promise<unknown> | void;
};

type OrganizationNameValues = { name: string };

export function OrganizationNameForm({ savedName, canUpdate, onSaved }: OrganizationNameFormProps) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<OrganizationNameValues>();
  const [pending, setPending] = useState(false);
  const watched = Form.useWatch('name', form);
  const dirty = typeof watched === 'string' && watched.trim() !== savedName;

  if (!canUpdate) {
    return <p className="org-readonly">当前岗位没有修改组织信息的权限，如需变更请联系系统管理员。</p>;
  }

  return <Form form={form} layout="vertical" className="org-edit" initialValues={{ name: savedName }}
    onFinish={async (values) => {
      const name = values.name.trim();
      setPending(true);
      try {
        await put('/api/system/organization', { name });
        // 对齐到实际存储值，避免首尾空格让表单在保存后仍显示「有未保存的改动」。
        form.setFieldsValue({ name });
        message.success('组织名称已更新');
        await onSaved();
      } catch (error) {
        message.error((error as Error).message);
      } finally {
        setPending(false);
      }
    }}>
    <Form.Item label="组织名称" name="name" rules={[
      { required: true, whitespace: true, message: '请输入组织名称' },
      { max: 200, message: '组织名称不能超过 200 个字符' },
    ]}>
      <Input maxLength={200} showCount placeholder="请输入组织名称" />
    </Form.Item>
    <p className={`org-edit-hint${dirty ? ' is-dirty' : ''}`} role="status">
      {dirty ? <><ExclamationCircleFilled /> 有未保存的改动</> : <><CheckCircleFilled /> 与已保存的名称一致</>}
    </p>
    <div className="org-edit-actions">
      <Button disabled={!dirty || pending} onClick={() => form.setFieldsValue({ name: savedName })}>重置</Button>
      <Button type="primary" htmlType="submit" loading={pending} disabled={!dirty}>保存</Button>
    </div>
  </Form>;
}
