/** system 模块的页面配置。 */
import type { ResourceConfig } from '../components/resource';
import { text, number, integer, lookup, date } from './factories';

export const systemResources: Record<string, ResourceConfig> = {
  'system.departments': {
    title: '部门', endpoint: '/api/system/departments', menuCode: 'system.departments',
    columns: [{ key: 'code', title: '编码' }, { key: 'name', title: '名称' }, { key: 'parent_id', title: '上级部门', lookup: 'departments' }, { key: 'is_active', title: '启用', toggle: true }],
    fields: [{ ...text('code', '部门编码', false), requiredOnEdit: true, placeholder: '留空自动生成，如 DEP-0001' }, text('name', '部门名称'), lookup('parent_id', '上级部门', 'departments', false), { name: 'is_active', label: '启用', kind: 'switch' }],
    allowCreate: true, allowEdit: true, allowDelete: true, singleColumn: true, initialValues: { is_active: true },
  },
  'system.roles': {
    title: '角色（岗位）', endpoint: '/api/system/roles', menuCode: 'system.roles',
    // 系统管理员是保留角色，后端禁止修改（409），所以它只显示状态不给开关。
    columns: [{ key: 'code', title: '编码' }, { key: 'name', title: '名称' },
      { key: 'is_active', title: '启用', toggle: true, toggleWhen: (row) => row.code !== 'system_admin' }],
    fields: [text('code', '角色编码'), text('name', '角色名称'), { name: 'is_active', label: '启用', kind: 'switch' }],
    allowCreate: true, allowEdit: true, allowDelete: true, singleColumn: true, initialValues: { is_active: true },
  },
  'system.users': {
    title: '用户', endpoint: '/api/system/users', menuCode: 'system.users',
    columns: [{ key: 'username', title: '用户名' }, { key: 'display_name', title: '姓名' }, { key: 'department_id', title: '部门', lookup: 'departments' }, { key: 'is_active', title: '启用', toggle: true }],
    fields: [text('username', '用户名'), text('display_name', '姓名'),
      // 不用 hiddenOnEdit：编辑时把字段整块拿掉会让后面所有字段挪位置，新增态和编辑态长得不一样。
      // 保留字段、置灰并说明去处，两个弹窗的排布就完全一致。
      { name: 'password', label: '初始密码', kind: 'password', required: true, minLength: 6,
        readOnlyOnEdit: true, placeholder: '至少 6 位',
        readOnlyPlaceholder: '编辑时不能修改，请用列表里的「重设密码」' },
      lookup('department_id', '部门', 'departments', false), { name: 'role_ids', label: '岗位角色', kind: 'multiLookup', lookup: 'roles', required: true }, { name: 'is_active', label: '启用', kind: 'switch' }],
    allowCreate: true, allowEdit: true, allowDelete: true, initialValues: { is_active: true },
  },
  'system.menus': {
    title: '菜单列表', endpoint: '/api/system/menus', menuCode: 'system.menus',
    columns: [{ key: 'code', title: '菜单编码' }, { key: 'name', title: '名称' }, { key: 'path', title: '路径' }, { key: 'sort_order', title: '顺序' }],
    fields: [text('code', '菜单编码'), text('name', '菜单名称'), { ...lookup('parent_id', '一级菜单', 'menus', false), topLevelOnly: true }, text('path', '路径', false), integer('sort_order', '顺序'), { name: 'is_active', label: '启用', kind: 'switch' }],
    allowCreate: true, allowEdit: true, allowDelete: true,
  },
  'system.opening_balances': {
    title: '期初往来余额', endpoint: '/api/reconciliation/opening-balances', menuCode: 'system.initialization', detailFromList: true,
    columns: [{ key: 'party_id', title: '往来单位', lookup: 'parties' }, { key: 'account_type', title: '账户类型' }, { key: 'effective_date', title: '生效日期' }, { key: 'amount', title: '期初余额' }],
    fields: [lookup('party_id', '往来单位', 'parties'), { name: 'account_type', label: '账户类型', kind: 'select', required: true,
      choices: [{ value: 'customer', label: '客户应收' }, { value: 'supplier', label: '供应商应付' }, { value: 'processor', label: '加工商应付' }] },
      date('effective_date', '生效日期'), number('amount', '期初余额')],
    allowCreate: true, allowEdit: true, allowDelete: true,
  },
};
