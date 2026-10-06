import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { ApartmentOutlined, AppstoreOutlined, ArrowRightOutlined, BankOutlined, CheckCircleOutlined, InboxOutlined, LockOutlined, ShopOutlined, ShoppingCartOutlined, ToolOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { Link } from 'react-router-dom';

type Step = { code: string; title: string; detail: string; optional?: boolean; tab?: string };
type DepartmentFlow = { key: string; name: string; subtitle: string; outcome: string; steps: Step[]; edges?: [number, number][] };

const flows: DepartmentFlow[] = [
  { key: 'sales', name: '销售部门', subtitle: '从客户订单到交付与回款', outcome: '完成客户交付，形成应收并跟进回款', steps: [
    { code: 'sales.orders', title: '销售订单', detail: '录入需求并提交审批，确认可执行订单。' },
    { code: 'sales.shipments', title: '销售出库', detail: '按订单分次发货，过账后扣减库存。' },
    { code: 'reconciliation.customers', title: '客户对账', detail: '核对交付形成的应收业务额。' },
    { code: 'reconciliation.receipts', title: '收款记录', detail: '登记客户回款，跟踪未结余额。' },
    { code: 'sales.orders', title: '销售订单完成', detail: '返回销售订单，查看订单完成情况。' },
    { code: 'sales.returns', title: '销售退货', detail: '有退货时关联原出库，办理退货或后续补发。', optional: true },
  ], edges: [[0, 1], [1, 2], [2, 3], [3, 4], [1, 5]] },
  { key: 'purchase', name: '采购部门', subtitle: '从采购需求到入库与付款', outcome: '保障物料供应，核清应付', steps: [
    { code: 'purchase.orders', title: '采购订单', detail: '确定供应商、物料和采购数量。' },
    { code: 'purchase.receipts', title: '采购入库', detail: '按订单分批收货，过账后增加库存。' },
    { code: 'purchase.returns', title: '采购退货', detail: '发现问题时按原入库办理退货。' },
    { code: 'reconciliation.suppliers', title: '供应商对账', detail: '核对入库和退货形成的应付。' },
    { code: 'reconciliation.payments', title: '付款记录', detail: '登记供应商付款，跟踪未结余额。' },
  ] },
  { key: 'inventory', name: '仓库部门', subtitle: '掌握结存与每次库存变化', outcome: '保持账实一致、流转可追溯', steps: [
    { code: 'inventory.query', title: '库存查询', detail: '查看各仓库物料和产品的当前结存。' },
    { code: 'inventory.transfers', title: '仓库调拨', detail: '记录一般仓库之间的库存转移。' },
    { code: 'inventory.stocktakes', title: '库存盘点', detail: '清点实物、提交差异并完成审批。' },
    { code: 'inventory.adjustments', title: '库存调整', detail: '按授权处理需要修正的库存。' },
    { code: 'inventory.movements', title: '库存流水', detail: '追溯入库、出库、消耗和调整的来源。' },
  ] },
  { key: 'production', name: '生产部门', subtitle: '从计划到领料和产出入库', outcome: '完成生产入库，记录实际消耗与产出', steps: [
    { code: 'production.plans', title: '生产计划', detail: '计算多级缺料，并拆分生产订单。' },
    { code: 'production.orders', title: '生产订单', detail: '按计划组织生产，确定订单产出项。' },
    { code: 'production.issues', title: '生产领料', detail: '从来源仓领料并调拨到现场仓。' },
    { code: 'production.consumptions', title: '实际消耗', detail: '登记生产过程中实际消耗的物料。' },
    { code: 'production.receipts', title: '生产入库', detail: '按订单产出办理入库；每张生产订单仅有一张入库单。' },
  ] },
  { key: 'outsourcing', name: '委外部门', subtitle: '管理外协供料、交付与结算', outcome: '掌握委外物料与加工往来', steps: [
    { code: 'outsourcing.orders', title: '委外单', detail: '确定加工商、产出和各项物料的供料方。' },
    { code: 'outsourcing.issues', title: '委外发料', detail: '我方供料时登记发出数量并扣减来源仓库存。' },
    { code: 'outsourcing.receipts', title: '委外入库', detail: '按实际交付分次入库。' },
    { code: 'reconciliation.processors', title: '委外对账', detail: '核对加工商往来业务额。' },
  ] },
  { key: 'finance', name: '财务部门', subtitle: '汇集客户、供应商与加工商往来', outcome: '看清各类往来及月末结余', steps: [
    { code: 'reconciliation.customers', title: '客户对账', detail: '核对客户应收与期初余额。' },
    { code: 'reconciliation.suppliers', title: '供应商对账', detail: '核对采购应付与期初余额。' },
    { code: 'reconciliation.processors', title: '委外对账', detail: '核对加工商应付与期初余额。' },
    { code: 'reconciliation.receipts', title: '收款记录', detail: '登记客户收款。' },
    { code: 'reconciliation.payments', title: '付款记录', detail: '登记供应商或加工商付款。' },
    { code: 'reconciliation.month_end', title: '月末汇总', detail: '查看各类往来在月末的汇总结果。' },
  ] },
];

const departmentIcons = {
  sales: <ShopOutlined />, purchase: <ShoppingCartOutlined />, inventory: <InboxOutlined />,
  production: <ToolOutlined />, outsourcing: <AppstoreOutlined />, finance: <BankOutlined />,
};

function FlowDiagram({ flow, menuPaths }: { flow: DepartmentFlow; menuPaths: Record<string, string> }) {
  const listRef = useRef<HTMLOListElement>(null);
  const cardsRef = useRef<(HTMLLIElement | null)[]>([]);
  const [paths, setPaths] = useState<{ path: string; optional: boolean }[]>([]);
  const [junctions, setJunctions] = useState<{ x: number; y: number }[]>([]);
  const [size, setSize] = useState({ width: 1, height: 1 });

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const measure = () => {
      const cards = cardsRef.current.slice(0, flow.steps.length);
      setSize({ width: list.clientWidth || 1, height: list.clientHeight || 1 });
      const edges = flow.edges ?? flow.steps.slice(0, -1).map((_, index): [number, number] => [index, index + 1]);
      const outgoing = new Map<number, number>();
      edges.forEach(([from]) => outgoing.set(from, (outgoing.get(from) ?? 0) + 1));
      const exitsRight = (from: number) => {
        const card = cards[from];
        return !!card && edges.filter(([source]) => source === from).every(([, to]) => {
          const next = cards[to];
          return !!next && next.offsetLeft >= card.offsetLeft + card.offsetWidth - 1;
        });
      };
      setJunctions([...outgoing].filter(([, count]) => count > 1).flatMap(([from]) => {
        const card = cards[from];
        return card ? [{ x: exitsRight(from) ? card.offsetLeft + card.offsetWidth : card.offsetLeft + card.offsetWidth / 2,
          y: exitsRight(from) ? card.offsetTop + card.offsetHeight / 2 : card.offsetTop + card.offsetHeight }] : [];
      }));
      setPaths(edges.map(([from, to]) => {
        const card = cards[from];
        const next = cards[to];
        const optional = !!flow.steps[to].optional;
        if (!card || !next) return { path: '', optional };
        const rightward = next.offsetLeft >= card.offsetLeft + card.offsetWidth - 1;
        if (rightward) {
          const sx = card.offsetLeft + card.offsetWidth;
          const sy = card.offsetTop + card.offsetHeight / 2;
          const ex = next.offsetLeft - 5;
          const ey = next.offsetTop + next.offsetHeight / 2;
          const tangent = Math.max(14, (ex - sx) * .42);
          const lift = Math.abs(ey - sy) < 8 ? 7 : 0;
          return { path: `M ${sx} ${sy} C ${sx + tangent} ${sy - lift}, ${ex - tangent} ${ey - lift}, ${ex} ${ey}`, optional };
        }
        const sx = card.offsetLeft + card.offsetWidth / 2;
        const sy = card.offsetTop + card.offsetHeight;
        const ex = next.offsetLeft + next.offsetWidth / 2;
        const ey = next.offsetTop - 5;
        const tangent = Math.max(26, (ey - sy) * .44);
        return { path: `M ${sx} ${sy} C ${sx} ${sy + tangent}, ${ex} ${ey - tangent}, ${ex} ${ey}`, optional };
      }));
    };
    measure();
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    if (observer) observer.observe(list);
    window.addEventListener('resize', measure);
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); };
  }, [flow]);

  return <ol className={`business-flow-steps${flow.edges ? ' is-branched' : ''}`} ref={listRef} style={{ '--flow-count': flow.edges ? 5 : flow.steps.length } as CSSProperties}>
    <svg className="business-flow-lines" viewBox={`0 0 ${size.width} ${size.height}`} preserveAspectRatio="none" aria-hidden="true">
      <defs><marker id="business-flow-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto" markerUnits="userSpaceOnUse">
        <path d="M 1 1 L 8 4.5 L 1 8" fill="none" stroke="#1668dc" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </marker></defs>
      {paths.map(({ path, optional }, index) => <path key={index} d={path} fill="none" stroke={optional ? '#9aafe0' : '#79a8e8'} strokeWidth="2.2" strokeLinecap="round" strokeDasharray={optional ? '5 5' : undefined} markerEnd="url(#business-flow-arrow)" />)}
    </svg>
    {junctions.map(({ x, y }, index) => <span key={index} className="business-flow-junction" style={{ left: x, top: y }} aria-hidden="true" />)}
    {flow.steps.map((step, index) => <li key={`${flow.key}-${index}`} className="business-flow-step" ref={(node) => { cardsRef.current[index] = node; }}>
      <span className="business-flow-step-number">{step.optional ? '支线' : String(index + 1).padStart(2, '0')}</span>
      <div className="business-flow-step-copy"><h4>{step.title}{step.optional && <span className="business-flow-optional">可选</span>}</h4><p>{step.detail}</p></div>
      {menuPaths[step.code] ? <Link className="business-flow-step-link" to={`${menuPaths[step.code]}${step.tab ? `?tab=${step.tab}` : ''}`} aria-label={`进入${step.title}`}>
        进入页面 <ArrowRightOutlined /></Link> : <span className="business-flow-step-locked"><LockOutlined /> 暂无权限</span>}
    </li>)}
  </ol>;
}

export function BusinessFlowPage({ menuPaths }: { menuPaths: Record<string, string> }) {
  const [selected, setSelected] = useState(() => flows.find((flow) => flow.steps.some((step) => menuPaths[step.code]))?.key ?? flows[0].key);
  const flow = flows.find((item) => item.key === selected) ?? flows[0];
  const accessible = flow.steps.filter((step) => menuPaths[step.code]).length;
  return <PageContainer title="业务全景">
    <div className="business-flow-page">
      <header className="business-flow-intro">
        <span className="business-flow-intro-icon"><ApartmentOutlined /></span>
        <div className="business-flow-intro-copy"><span className="business-flow-eyebrow">BUSINESS MAP · 业务路径</span>
          <h2>从部门视角，看清每一步业务。</h2>
          <p>选择部门查看流程，点击有权限的节点进入业务页面。</p></div>
        <div className="business-flow-summary"><strong>06</strong><span>部门流程</span></div>
      </header>
      <nav className="business-flow-nav" aria-label="选择部门">
        {flows.map((item) => <button key={item.key} type="button" className={`business-flow-nav-item${item.key === flow.key ? ' is-active' : ''}`}
          aria-current={item.key === flow.key ? 'page' : undefined} onClick={() => setSelected(item.key)}>
          <span className="business-flow-nav-icon">{departmentIcons[item.key as keyof typeof departmentIcons]}</span><strong>{item.name}</strong>
        </button>)}
      </nav>
      <section className="business-flow-detail" aria-label={`${flow.name}操作流程`}>
        <div className="business-flow-detail-head"><div><span className="business-flow-eyebrow">DEPARTMENT WORKFLOW</span>
          <h3>{flow.name}<span className="business-flow-detail-subtitle">{flow.subtitle}</span></h3></div>
          <div className="business-flow-head-meta"><span className="business-flow-count">{accessible}/{flow.steps.length} 个节点可进入</span>
            <span className="business-flow-legend"><i /> 主流程 <i className="is-optional" /> 可选分支</span></div></div>
        <div className="business-flow-canvas">
          <div className="business-flow-canvas-label"><span>起点</span><span>按箭头方向推进</span><span>结束</span></div>
          <FlowDiagram key={flow.key} flow={flow} menuPaths={menuPaths} />
        </div>
        <footer className="business-flow-outcome"><CheckCircleOutlined /><span>流程目标：{flow.outcome}</span></footer>
      </section>
    </div>
  </PageContainer>;
}
