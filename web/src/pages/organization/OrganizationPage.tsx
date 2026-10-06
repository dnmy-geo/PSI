import { Alert, Button, Card, Descriptions, Skeleton } from 'antd';
import { ApartmentOutlined, ArrowRightOutlined, AuditOutlined, ClusterOutlined, DatabaseOutlined, FileSearchOutlined, MenuOutlined, SafetyCertificateOutlined, TeamOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { get, type Row } from '../../api/client';
import { OrganizationNameForm } from './OrganizationNameForm';

// 与 server/app/system/menu_seed.py 的 system 分组子菜单一一对应；页面路径由服务端按菜单码生成。
const shortcutLinks = [
  { code: 'system.departments', name: '部门', icon: <ApartmentOutlined /> },
  { code: 'system.roles', name: '角色', icon: <SafetyCertificateOutlined /> },
  { code: 'system.users', name: '用户', icon: <TeamOutlined /> },
  { code: 'system.menus', name: '菜单列表', icon: <MenuOutlined /> },
  { code: 'system.permissions', name: '权限配置', icon: <ClusterOutlined /> },
  { code: 'system.approvals', name: '审批配置', icon: <AuditOutlined /> },
  { code: 'system.initialization', name: '数据初始化', icon: <DatabaseOutlined /> },
  { code: 'system.audit_logs', name: '操作日志', icon: <FileSearchOutlined /> },
];

export type OrganizationPageProps = {
  /** 当前用户可见菜单的「菜单码 → 路径」映射；只有存在的键才渲染入口，因此它同时充当权限判断。 */
  menuPaths?: Record<string, string>;
};

export function OrganizationPage({ menuPaths = {} }: OrganizationPageProps) {
  const query = useQuery({ queryKey: ['organization'], queryFn: () => get<Row>('/api/system/organization') });
  const permissions = useQuery({ queryKey: ['my-permissions'], queryFn: () => get<Record<string, string[]>>('/api/system/my-permissions') });
  const canUpdate = (permissions.data?.['system.organization'] ?? []).includes('update');

  const name = String(query.data?.name ?? '');
  const code = String(query.data?.code ?? '');
  const isActive = Boolean(query.data?.is_active);
  const links = shortcutLinks.flatMap((link) => {
    const path = menuPaths[link.code];
    return path ? [{ ...link, path }] : [];
  });

  return <PageContainer title="组织">
    <div className="org-page">
      {query.isPending ? <Card><Skeleton active paragraph={{ rows: 2 }} /></Card>
        : query.isError ? <Alert type="error" showIcon message="组织信息加载失败"
            description={(query.error as Error).message}
            action={<Button size="small" onClick={() => query.refetch()}>重试</Button>} />
        : <>
          <header className="org-identity">
            <span className="org-identity-icon"><ApartmentOutlined /></span>
            <div className="org-identity-copy">
              <span className="org-identity-eyebrow">ORGANIZATION · 组织</span>
              <h2 title={name || undefined}>{name || '—'}</h2>
              <p>组织编码 · <span className="org-identity-code">{code || '—'}</span></p>
            </div>
            <span className={`org-status${isActive ? '' : ' is-inactive'}`}>{isActive ? '启用' : '停用'}</span>
          </header>
          <div className="org-grid">
            <Card title="组织档案">
              <Descriptions column={1} bordered items={[
                { key: 'code', label: '组织编码', children: code || '—' },
                { key: 'name', label: '组织名称', children: name || '—' },
                { key: 'active', label: '状态', children: isActive ? '启用' : '停用' },
              ]} />
            </Card>
            <Card title="修改组织名称">
              <OrganizationNameForm savedName={name} canUpdate={canUpdate} onSaved={() => query.refetch()} />
            </Card>
          </div>
          <Card title="组织相关设置" extra={<span className="org-shortcuts-note">仅显示当前岗位可访问的菜单</span>}>
            {links.length === 0
              ? <p className="org-shortcuts-empty">暂无其他可访问的系统设置，请联系系统管理员分配权限。</p>
              : <nav className="org-shortcuts" aria-label="组织相关设置">
                {links.map((link) => <Link className="org-shortcut" key={link.code} to={link.path} aria-label={`进入${link.name}`}>
                  <span className="org-shortcut-icon">{link.icon}</span>
                  <span>{link.name}</span>
                  <ArrowRightOutlined className="org-shortcut-arrow" />
                </Link>)}
              </nav>}
          </Card>
        </>}
    </div>
  </PageContainer>;
}
