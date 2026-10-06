
export const statusLabels: Record<string, string> = {
  draft: '草稿', pending_approval: '待审批', approved: '已审批', rejected: '已驳回',
  open: '进行中', closed: '已关闭', completed: '已完成', counting: '清点中',
  posted: '已过账', reversed: '已冲销', cancelled: '已取消', pending: '待处理',
};

/** 详情里不展示的字段：都是数据库标识，界面上只是裸 UUID，没有任何信息量。 */
export const HIDDEN_DETAIL_FIELDS = new Set(['id', 'organization_id', 'created_by']);

export /** 详情里会直接露出的枚举值（配置里没有 choices 可查的那些）。 */
const VALUE_LABELS: Record<string, string> = {
  customer: '客户', supplier: '供应商', processor: '加工商',
  raw_material: '原材料', semi_finished: '半成品', finished: '成品',
  normal: '普通出库', replacement: '补发出库', receipt: '收款', payment: '付款',
  sales_order: '销售订单', purchase_order: '采购订单', outsourcing_order: '委外单',
};

/**
 * 详情抽屉里字段名到中文的兜底对照。优先用配置里的 label/title，
 * 这里只覆盖接口返回但配置没声明的字段（多为服务端算出来的派生列），
 * 否则抽屉里会直接露出英文 key。
 */
export const FIELD_LABELS: Record<string, string> = {
  // 通用
  id: 'ID', organization_id: '组织', code: '编码', name: '名称', remark: '备注',
  status: '状态', is_active: '启用', sort_order: '顺序', version: '版本',
  created_at: '创建时间', updated_at: '修改时间', created_by: '创建人', posted_at: '过账时间', cutoff_at: '截止时间',
  document_no: '单号', document_date: '单据日期', delivery_date: '交货日期',
  // 人员与组织
  username: '用户名', display_name: '姓名', department_id: '部门',
  contact_name: '联系人', contact_phone: '联系电话', path: '路径', parent_id: '上级',
  admin_only: '管理员专属',
  // 往来与单据关联
  party_id: '往来单位', customer_id: '客户', supplier_id: '供应商', processor_id: '加工商',
  item_id: '物料', item_type: '类型', base_unit_id: '基本单位', category_id: '物料分类',
  parent_item_id: '产出物料', child_item_id: '子物料', warehouse_id: '仓库',
  source_warehouse_id: '来源仓库', target_warehouse_id: '目标仓库',
  unit_id: '单位', unit_code: '单位', unit_price: '单价', amount: '金额',
  sales_order_id: '销售订单', purchase_order_id: '采购订单', production_plan_id: '生产计划',
  production_order_id: '生产订单', outsourcing_order_id: '委外单', stocktake_id: '盘点单',
  original_shipment_id: '原出库单', source_id: '关联单据', source_type: '关联单据类型',
  reason: '原因', detail: '说明', close_remark: '关闭备注', shipment_type: '出库类型',
  account_type: '账户类型', record_type: '记录类型', is_opening_reference: '期初来源单据',
  role_ids: '岗位角色', types: '身份',
  // 明细：数量
  quantity: '数量', quantity_base: '数量（基本单位）', quantity_delta_base: '变动数量',
  planned_quantity_base: '计划数量', allocated_quantity_base: '已分配数量',
  remaining_quantity_base: '剩余未分配数量', expected_quantity_base: '预计数量',
  issued_quantity_base: '已发料数量', received_quantity_base: '已入库数量',
  shipped_quantity_base: '已出库数量', unshipped_quantity_base: '未出库数量',
  unreceived_quantity_base: '未入库数量', counted_quantity_base: '实盘数量',
  book_quantity_base: '账面数量', difference_quantity_base: '差异数量',
  bom_quantity_base: 'BOM 用量', loss_quantity_base: '损耗量',
  conversion_factor: '换算系数', supply_party: '供料方',
  // 明细：来源行
  sales_order_line_id: '订单明细', sales_shipment_line_id: '原出库明细',
  purchase_order_line_id: '订单明细', production_plan_line_id: '计划行',
  production_order_output_id: '生产订单产出', outsourcing_material_line_id: '委外物料',
  outsourcing_output_line_id: '委外产出', replacement_return_line_id: '补发对应退货明细',
};

export const APPROVAL_TASK_STATUS: Record<string, string> = {
  pending: '待审批', approved: '已同意', rejected: '已驳回', skipped: '已跳过',
};
export const APPROVAL_INSTANCE_STATUS: Record<string, string> = {
  pending: '审批中', approved: '已通过', rejected: '已驳回',
};

