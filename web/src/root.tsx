import { useState } from 'react';
import { App as AntApp, Badge, Button, Result, Spin } from 'antd';
import { LoginForm, ProFormText, ProLayout } from '@ant-design/pro-components';
import { ApartmentOutlined, AppstoreOutlined, BarChartOutlined, DatabaseOutlined, FileTextOutlined, HomeOutlined, InboxOutlined, LogoutOutlined, SettingOutlined, ShopOutlined, ShoppingCartOutlined, TeamOutlined, ToolOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ApiError, get, getPage, post, setCsrfToken, type Session } from './api/client';
import { pageForCode } from './pages/registry';

type MenuRow = { id: string; parent_id: string | null; code: string; name: string; path: string | null };

function menuIcon(name: string) {
  if (name.includes('工作台')) return <HomeOutlined />;
  if (name.includes('业务全景')) return <ApartmentOutlined />;
  if (name.includes('销售')) return <ShopOutlined />;
  if (name.includes('采购')) return <ShoppingCartOutlined />;
  if (name.includes('库存')) return <InboxOutlined />;
  if (name.includes('生产')) return <ToolOutlined />;
  if (name.includes('委外')) return <AppstoreOutlined />;
  if (name.includes('对账')) return <FileTextOutlined />;
  if (name.includes('报表')) return <BarChartOutlined />;
  if (name.includes('基础')) return <DatabaseOutlined />;
  if (name.includes('系统')) return <SettingOutlined />;
  return <TeamOutlined />;
}

function Login({ onLogin }: { onLogin: (session: Session) => void }) {
  const { message } = AntApp.useApp();
  const [pending, setPending] = useState(false);
  return <div className="login-shell">
    <div className="login-fluid" aria-hidden="true">
      <span className="login-fluid-blob login-fluid-blob-one" />
      <span className="login-fluid-blob login-fluid-blob-two" />
      <span className="login-fluid-blob login-fluid-blob-three" />
      <span className="login-fluid-blob login-fluid-blob-four" />
    </div>
    <main className="login-layout">
      <section className="login-intro" aria-label="平台介绍">
        <div className="login-brand"><span className="login-brand-mark">P</span><span>PSI <span className="login-brand-light">进销存</span></span></div>
        <div className="login-intro-content">
          <span className="login-eyebrow">工厂业务协同平台</span>
          <h1>让业务流转，<br /><span>更清晰。</span></h1>
          <p>从采购、生产到库存与销售，在同一个工作台中高效协作。</p>
          <div className="login-flow" aria-hidden="true"><span>采购</span><i /><span>生产</span><i /><span>库存</span><i /><span>销售</span></div>
        </div>
        <div className="login-intro-footer">PSI · 工厂进销存管理系统</div>
      </section>
      <section className="login-card" aria-label="登录">
        <div className="login-card-top"><span className="login-card-icon">P</span><span>PSI 工作台</span></div>
        <h2 className="login-heading">欢迎回来</h2>
        <p className="login-subtitle">登录账号，继续处理今天的业务。</p>
    <LoginForm< { username: string; password: string } >
      logo={false} title={false} subTitle={false} submitter={{ searchConfig: { submitText: '登录' }, submitButtonProps: { loading: pending, block: true } }}
      onFinish={async (values) => {
        setPending(true);
        try {
          const session = await post<Session>('/api/auth/login', values);
          onLogin(session);
          return true;
        } catch (error) {
          message.error(error instanceof Error ? error.message : '登录失败');
          return false;
        } finally { setPending(false); }
      }}
    >
      <ProFormText name="username" label="用户名" rules={[{ required: true }]} />
      <ProFormText.Password name="password" label="密码" rules={[{ required: true }]} />
    </LoginForm>
        <p className="login-card-footer">安全、便捷地连接每一道业务流程</p>
      </section>
    </main>
  </div>;
}

export function Root() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [session, setSession] = useState<Session | null>(null);
  const me = useQuery({ queryKey: ['session'], queryFn: () => get<Session>('/api/auth/me'), retry: false });
  const active = session ?? me.data ?? null;
  if (active) setCsrfToken(active.csrf_token);
  const menus = useQuery({ queryKey: ['menus', active?.user_id], queryFn: () => get<MenuRow[]>('/api/system/my-menus'), enabled: !!active });
  // 侧边栏「工作台」右上角的待审批数量：口径就是工作台「我的待办」那批任务
  // （后端只返回当前用户、当前层级、还没处理的）。没待办时不显示角标。
  const pendingApprovals = useQuery({
    queryKey: ['my-pending-approvals', active?.user_id], enabled: !!active,
    queryFn: async () => (await getPage<MenuRow[]>('/api/approval/tasks/mine', { limit: 1 })).total ?? 0,
    // 审批是别人发起的，页面不主动刷新就会一直显示旧数字；一分钟兜一次，审批后由工作台主动作废。
    refetchInterval: 60_000,
  });

  if (me.isPending && !session) return <div className="login-shell"><Spin size="large" /></div>;
  if (!active) return <Login onLogin={(value) => { setCsrfToken(value.csrf_token); setSession(value); queryClient.setQueryData(['session'], value); navigate('/'); }} />;
  if (menus.isPending) return <div className="login-shell"><Spin size="large" /></div>;
  if (menus.error) return <Result status="error" title="菜单加载失败" subTitle={(menus.error as Error).message} extra={<Button onClick={() => menus.refetch()}>重试</Button>} />;

  const visible = menus.data ?? [];
  const children = visible.filter((menu) => menu.parent_id);
  const parents = visible.filter((menu) => !menu.parent_id);
  const workbench = parents.find((menu) => menu.code === 'workbench');
  const workbenchAccess = {
    overview: visible.some((menu) => menu.code === 'workbench.overview'),
    tasks: visible.some((menu) => menu.code === 'workbench.tasks'),
    alerts: visible.some((menu) => menu.code === 'workbench.alerts'),
  };
  // The three workbench child codes remain permission scopes; navigation uses one leaf route.
  const route = { path: '/', routes: parents.map((parent) => ({
    path: parent.code === 'workbench' ? '/workbench' : parent.path ?? `/${parent.code}`,
    name: parent.name,
    icon: menuIcon(parent.name),
    routes: parent.code === 'workbench' || parent.code === 'business_flow' ? undefined : children.filter((child) => child.parent_id === parent.id).map((child) => ({
      path: child.path ?? `/${child.code.replace('.', '/')}`, name: child.name,
    })),
  })) };
  const current = location.pathname === '/workbench' ? workbench : visible.find((menu) => menu.path === location.pathname);
  const menuPaths = Object.fromEntries(children.filter((menu) => menu.path).map((menu) => [menu.code, menu.path!])) as Record<string, string>;
  const page = current ? pageForCode(current.code, current.name, workbenchAccess, menuPaths) : null;
  const home = workbench ? '/workbench' : children[0]?.path ?? '/';
  const legacyWorkbenchPath = ['/workbench/overview', '/workbench/tasks', '/workbench/alerts'].includes(location.pathname);
  const logout = async () => {
    try { await post('/api/auth/logout'); } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) throw error;
    }
    setCsrfToken(''); setSession(null); queryClient.clear(); navigate('/');
  };

  return <ProLayout
    className="psi-app" title="PSI 进销存" logo={false} layout="side" fixedHeader fixSiderbar route={route}
    location={{ pathname: location.pathname }}
    menuItemRender={(item, dom) => {
      if (!item.path) return dom;
      // 「工作台」右上角挂待审批数量（红色角标；为 0 时 antd 自己不显示）。
      if (item.path === '/workbench' && (pendingApprovals.data ?? 0) > 0) {
        return <Link to={item.path} className="psi-menu-pending">{dom}
          <Badge count={pendingApprovals.data} size="small" /></Link>;
      }
      return <Link to={item.path}>{dom}</Link>;
    }}
    menuHeaderRender={(_logo, _title, props) => <div className="psi-brand">
      <span className="psi-brand-symbol">P</span>
      {!props?.collapsed && <span className="psi-brand-copy"><strong>PSI</strong><small>进销存工作台</small></span>}
    </div>}
    menuFooterRender={(props) => <div className={`psi-account${props?.collapsed ? ' psi-account-collapsed' : ''}`}>
      <span className="psi-account-avatar" aria-hidden="true">{active.display_name.slice(0, 1)}</span>
      {!props?.collapsed && <span className="psi-account-copy"><strong>{active.display_name}</strong><small>{active.username}</small></span>}
      <Button type="text" aria-label="退出登录" title="退出登录" icon={<LogoutOutlined />} onClick={logout} />
    </div>}
  >
    {location.pathname === '/' || legacyWorkbenchPath ? <Navigate to={home} replace /> :
      <div className="psi-page-transition" key={location.pathname}>
        {page ?? <Result status="404" title="未找到页面" subTitle="请从左侧菜单进入功能页面" />}
      </div>}
  </ProLayout>;
}
