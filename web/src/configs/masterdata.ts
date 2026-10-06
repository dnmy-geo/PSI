/** masterdata 模块的页面配置。 */
import type { ResourceConfig } from '../components/resource';
import { text, number, integer, lookup } from './factories';

export const masterdataResources: Record<string, ResourceConfig> = {
  'masterdata.warehouses': {
    title: '仓库', endpoint: '/api/warehouses', menuCode: 'masterdata.warehouses',
    columns: [{ key: 'code', title: '编码' }, { key: 'name', title: '仓库名称' }, { key: 'is_active', title: '启用', toggle: true }],
    fields: [text('code', '仓库编码'), text('name', '仓库名称'), { name: 'is_active', label: '启用', kind: 'switch' }],
    allowCreate: true, allowEdit: true, allowDelete: true, initialValues: { is_active: true },
  },
  'masterdata.units': {
    title: '计量单位', endpoint: '/api/units', menuCode: 'masterdata.units',
    // 各列宽度按剩余空间均分（操作列固定 320），避免某一列吃掉全部留白。
    columns: [{ key: 'code', title: '编码', width: 130 }, { key: 'name', title: '名称', width: 140 },
      { key: 'precision_scale', title: '小数位数', width: 130 },
      { key: 'base_unit_id', title: '基本单位', lookup: 'units', width: 140 },
      { key: 'base_quantity', title: '基本数量', width: 130 },
      // 被关联单位：哪些单位把这一条当作基本单位。有值时本行不能再选基本单位（后端也会拦）。
      { key: 'related_units', title: '被关联单位', arrayField: 'code', width: 128 },
      { key: 'is_active', title: '启用', toggle: true, width: 96 }],
    fields: [{ ...text('code', '单位编码'), placeholder: '如 BOX' }, { ...text('name', '单位名称'), placeholder: '如 箱' },
      { ...integer('precision_scale', '小数位数'), placeholder: '数量显示保留几位小数，如 3 表示 0.001' },
      // 只能选「自己没有基本单位」的单位，层级因此最多两层。
      { ...lookup('base_unit_id', '基本单位', 'units', false),
        filter: (row) => !row.base_unit_id, disabledWhenFilled: 'related_units',
        placeholder: '留空表示本单位就是基本单位' },
      // number() 默认 required:true（单据明细的数量确实必填），这里要覆盖掉：
      // 两个字段都留空表示本单位就是基本单位，只有选了基本单位才要求填数量。
      { ...number('base_quantity', '基本数量'), required: false, requiredWhenFilled: 'base_unit_id',
        placeholder: '1 个本单位等于几个基本单位，如 12' },
      { name: 'is_active', label: '启用', kind: 'switch' }],
    allowCreate: true, allowEdit: true, allowDelete: true, initialValues: { precision_scale: 0, is_active: true },
  },
  'masterdata.categories': {
    title: '物料分类', endpoint: '/api/item-categories', menuCode: 'masterdata.categories',
    // 分类没有启停概念：item_categories 表没有 is_active 列，接口也不返回该字段，
    // 原先的「启用」列恒为「—」、表单里那个开关也存不进去，一并移除。
    columns: [{ key: 'code', title: '编码' }, { key: 'name', title: '名称' }, { key: 'parent_id', title: '上级分类', lookup: 'categories' }],
    fields: [text('code', '分类编码'), text('name', '分类名称'), lookup('parent_id', '上级分类', 'categories', false)],
    allowCreate: true, allowEdit: true, allowDelete: true,
  },
  'masterdata.items': {
    title: '物料与产品', endpoint: '/api/items', menuCode: 'masterdata.items',
    columns: [{ key: 'code', title: '编码' }, { key: 'name', title: '名称' }, { key: 'item_type', title: '类型' }, { key: 'base_unit_id', title: '基本单位', lookup: 'units' }, { key: 'is_active', title: '启用', toggle: true }],
    fields: [text('code', '物料编码'), text('name', '物料名称'), { name: 'item_type', label: '类型', kind: 'select', required: true,
      choices: [{ value: 'raw_material', label: '原材料' }, { value: 'semi_finished', label: '半成品' }, { value: 'finished', label: '成品' }], hiddenOnEdit: true },
      { ...lookup('base_unit_id', '基本单位', 'units'), hiddenOnEdit: true }, lookup('category_id', '分类', 'categories', false),
      { name: 'is_active', label: '启用', kind: 'switch' }],
    allowCreate: true, allowEdit: true, allowDelete: true, initialValues: { is_active: true },
  },
  'masterdata.boms': {
    title: '多级用料清单', endpoint: '/api/boms', menuCode: 'masterdata.boms',
    // 列表按 BOM 头分页，每行带多级展开的用料树：根行是产出物料，子行是用料（含用量），
    // 子物料若自己也启用了 BOM 会继续向下展开。子行没有单据，故用 row_kind 区分。
    columns: [{ key: 'item_id', title: '物料', lookup: 'items', width: 374 },
      { key: 'quantity_base', title: '用量', unitKey: 'unit_code', width: 180 },
      { key: 'version', title: '版本', width: 170 },
      // 用只读标签而非开关：BOM 的启用只能走「启用版本」动作，编辑接口不接受 is_active。
      { key: 'is_active', title: '启用', flag: true, width: 170 }],
    fields: [lookup('parent_item_id', '产出物料', 'items'), integer('version', '版本')],
    lines: [{ name: 'lines', label: '用料明细', fields: [lookup('child_item_id', '子物料', 'items'), number('quantity_base', '基本单位用量'), integer('sort_order', '顺序')] }],
    actions: [{ key: 'activate', label: '启用版本' }], allowCreate: true, allowEdit: true, allowDelete: true,
    serverPaging: true,
    tree: { isResourceRow: (row) => row.row_kind === 'bom', rowKey: 'path_key' },
  },
  'masterdata.customers': {
    title: '客户', endpoint: '/api/parties', menuCode: 'masterdata.customers',
    listParams: { party_type: 'customer' },
    columns: [{ key: 'code', title: '编码' }, { key: 'name', title: '名称' }, { key: 'contact_name', title: '联系人' }, { key: 'contact_phone', title: '电话' }],
    fields: [text('code', '编码'), text('name', '名称'), text('contact_name', '联系人', false), text('contact_phone', '电话', false), { name: 'is_active', label: '启用', kind: 'switch' }],
    allowCreate: true, allowEdit: true, allowDelete: true, initialValues: { is_active: true },
    createTransform: (values) => ({ ...values, types: ['customer'] }),
    editTransform: (values, original) => ({ ...values, types: original.types }),
  },
  'masterdata.suppliers': {
    title: '供应商', endpoint: '/api/parties', menuCode: 'masterdata.suppliers',
    listParams: { party_type: 'supplier' },
    columns: [{ key: 'code', title: '编码' }, { key: 'name', title: '名称' }, { key: 'contact_name', title: '联系人' }, { key: 'contact_phone', title: '电话' }],
    fields: [text('code', '编码'), text('name', '名称'), text('contact_name', '联系人', false), text('contact_phone', '电话', false), { name: 'is_active', label: '启用', kind: 'switch' }],
    allowCreate: true, allowEdit: true, allowDelete: true, initialValues: { is_active: true },
    createTransform: (values) => ({ ...values, types: ['supplier'] }),
    editTransform: (values, original) => ({ ...values, types: original.types }),
  },
  'masterdata.processors': {
    title: '委外加工商', endpoint: '/api/parties', menuCode: 'masterdata.processors',
    listParams: { party_type: 'processor' },
    columns: [{ key: 'code', title: '编码' }, { key: 'name', title: '名称' }, { key: 'contact_name', title: '联系人' }, { key: 'contact_phone', title: '电话' }],
    fields: [text('code', '编码'), text('name', '名称'), text('contact_name', '联系人', false), text('contact_phone', '电话', false), { name: 'is_active', label: '启用', kind: 'switch' }],
    allowCreate: true, allowEdit: true, allowDelete: true, initialValues: { is_active: true },
    createTransform: (values) => ({ ...values, types: ['processor'] }),
    editTransform: (values, original) => ({ ...values, types: original.types }),
  },
};
