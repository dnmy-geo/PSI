import type { ReactNode } from 'react';
import type { Row } from '../../api/client';

export type Lookup = 'items' | 'units' | 'warehouses' | 'parties' | 'categories' | 'roles' | 'departments' | 'menus' | 'salesOrders' | 'purchaseOrders' | 'productionPlans' | 'productionOrders' | 'outsourcingOrders' | 'salesShipments' | 'salesReturns' | 'purchaseReceipts' | 'productionIssues' | 'outsourcingIssues';
export type FieldSpec = {
  name: string;
  label: string;
  kind?: 'text' | 'number' | 'integer' | 'date' | 'select' | 'lookup' | 'switch' | 'password' | 'textarea' | 'multiLookup' | 'sourceLine' | 'hidden' | 'stock' | 'item' | 'unit';
  required?: boolean;
  requiredOnEdit?: boolean;
  lookup?: Lookup;
  partyType?: 'customer' | 'supplier' | 'processor';
  topLevelOnly?: boolean;
  showWhen?: { name: string; equals: string };
  choices?: { label: string; value: string }[];
  source?: { parent: string; endpoint: string; lineKey?: string };
  hiddenOnEdit?: boolean;
  readOnlyOnEdit?: boolean;
  placeholder?: string;
  /** 编辑时置灰的话术。不给就沿用 placeholder。 */
  readOnlyPlaceholder?: string;
  /** 最短位数，配合后端的 min_length 在提交前先给提示。 */
  minLength?: number;
  /** 进一步筛掉不符合条件的下拉选项（在 lookup 结果上再过滤，如「只能选还没有基本单位的单位」）。 */
  filter?: (row: Row) => boolean;
  /** 同一表单里这个字段有值时禁用本字段（如已有被关联单位就不能再选基本单位）。 */
  disabledWhenFilled?: string;
  /** 单位字段跟随哪个物料字段：只列出该物料的基本单位及其下级单位，避免选到换算不通的单位。 */
  unitFor?: string;
  /** kind='stock' 时：看哪个物料字段（行内相对名，默认 item_id）与哪个仓库字段（单据级，默认 warehouse_id）。 */
  stockItem?: string;
  stockWarehouse?: string;
  /** kind='item' / kind='unit' 时：看哪个行内字段取物料（默认 item_id）。 */
  itemSource?: string;
  /** 同一表单里这个字段有值时才必填（如选了基本单位就必须填基本数量，两者都不填则都留空）。 */
  requiredWhenFilled?: string;
  /**
   * 数字字段的下限，默认 0（数量不为负）。
   * 必须显式给：@ant-design/pro-field 的 Digit 渲染把 min 写死成 0，
   * 而 ProFormDigit 传下去的 `min: undefined` 会被丢掉，负数会被静默夹成 0。
   */
  min?: number;
};
export type ActionSpec = { key: string; label: string; statuses?: string[]; prompt?: 'remark' | 'reason' | 'none'; danger?: boolean; path?: string; permission?: string };
export type ResourceConfig = {
  title: string;
  endpoint: string;
  menuCode: string;
  columns: {
    key: string; title: string; lookup?: Lookup; toggle?: boolean;
    /** 该行是否可切换（如系统保留角色不允许停用）。返回 false 时渲染成只读标签，不给一个点了必报错的开关。 */
    toggleWhen?: (row: Row) => boolean;
    /** 该列是数量、单位逐行不同时，指定单位取自哪个字段（如 'unit_code'），渲染成「数值 单位」。 */
    unitKey?: string;
    /** 固定列宽；不写则由 antd 按剩余空间分配，容易让某一列吃掉全部留白。 */
    width?: number;
    /** 该列是对象数组时取哪个字段展示（如被关联单位取 code），空数组显示「—」。 */
    arrayField?: string;
    /** 数值列渲染成标签：为 0 显示 zero，否则显示 nonzero（如未出库量 → 已发完/未发完）。 */
    zeroTag?: { zero: string; nonzero: string };
    /**
     * 布尔列渲染成只读的是/否标签。
     * 需要就地切换时用 toggle；但如果该资源的启用与否由专门的动作控制
     * （例如 BOM 只能用「启用版本」切换、且编辑接口不接受 is_active），
     * 放开关只会点出一串报错，这时应该用 flag。
     */
    flag?: boolean;
  }[];
  fields?: FieldSpec[];
  /** 表单字段单列排布，适合字段少或名称较长的资料页。 */
  singleColumn?: boolean;
  /** 基本信息一行排三个字段（默认两个）；长文本字段仍然独占一行。 */
  threeColumn?: boolean;
  lines?: { name: string; label: string; fields: FieldSpec[]; optional?: boolean }[];
  /**
   * 只在详情里出现的明细字段（明细由别的入口维护，比如盘点的实盘数是在「录入实盘数」弹窗里填的）。
   * 作用是让详情表的列名和外键翻译走与 lines 相同的规则，但不参与新建/编辑表单的渲染。
   */
  detailLines?: { name: string; label: string; fields: FieldSpec[] }[];
  autoNumberPrefix?: string;
  /** 自动单号那一行显示的名字，默认「订单单号」。 */
  autoNumberLabel?: string;
  inlineLines?: boolean;
  /** 明细列较多（如出库单 5 列）时用更宽的弹窗，避免下拉文本被截断。 */
  wideModal?: boolean;
  /** 新建/编辑弹窗的宽度，覆盖上面的默认档位（如 '80%'）。 */
  modalWidth?: number | string;
  actions?: ActionSpec[];
  detailEndpoint?: string;
  detailFromList?: boolean;
  /** 详情里附带审批进度：值为审批单据类型（如 'sales_order'），不设则不请求。 */
  approvalType?: 'sales_order' | 'stocktake';
  serverPaging?: boolean;
  allowCreate?: boolean;
  allowEdit?: boolean;
  allowDelete?: boolean;
  /**
   * 树形列表：行的 children 由后端下发，antd 自动按树渲染。
   * isResourceRow 用来区分「资源本身」和展开出来的子行——子行没有自己的单据，
   * 因此不显示启用开关，也不显示编辑/删除按钮。
   * rowKey 指定按路径唯一的行键字段：同一份明细可能挂在多个父节点下，
   * 直接用明细 id 会撞键，收起时子树收不干净。
   */
  tree?: { isResourceRow: (row: Row) => boolean; rowKey: string };
  writePermissions?: Partial<Record<'create' | 'update' | 'delete', string>>;
  initialValues?: Row;
  listParams?: Record<string, string>;
  createTransform?: (values: Row) => Row;
  editTransform?: (values: Row, original: Row) => Row;
  customAction?: (row: Row, refresh: () => void, can: (action: string) => boolean) => ReactNode;
};

