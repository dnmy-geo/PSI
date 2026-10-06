import type { FieldSpec } from '../components/resource';

export const text = (name: string, label: string, required = true): FieldSpec => ({ name, label, required });
export const number = (name: string, label: string): FieldSpec => ({ name, label, kind: 'number', required: true });
export const integer = (name: string, label: string): FieldSpec => ({ name, label, kind: 'integer', required: true });
export const lookup = (name: string, label: string, source: FieldSpec['lookup'], required = true): FieldSpec => ({ name, label, kind: 'lookup', lookup: source, required });
export const date = (name = 'document_date', label = '单据日期'): FieldSpec => ({ name, label, kind: 'date', required: true });
export const remark: FieldSpec = { name: 'remark', label: '备注', kind: 'textarea' };
export const status = { key: 'status', title: '状态' };
export const docColumns = [{ key: 'document_no', title: '单号' }, { key: 'document_date', title: '日期' }, status];
export const docFields = [text('document_no', '单号'), date()];
export const itemLine = [lookup('item_id', '物料', 'items'), { ...lookup('unit_id', '单位', 'units'), unitFor: 'item_id' }, number('quantity', '数量')];
export const sourceLine = (name: string, label: string, parent: string, endpoint: string, lineKey = 'lines', required = true): FieldSpec => ({
  name, label, kind: 'sourceLine', required, source: { parent, endpoint, lineKey },
});
export const linkedLine = (name: string, label: string, parent: string, endpoint: string, lineKey = 'lines',
  // 来源行之后、隐藏物料之前插入的字段（如只读的「物料」列）。
  between: FieldSpec[] = []): FieldSpec[] => [
  sourceLine(name, label, parent, endpoint, lineKey), ...between, { name: 'item_id', label: '物料', kind: 'hidden' },
  { ...lookup('unit_id', '单位', 'units'), unitFor: 'item_id' }, number('quantity', '数量'),
];
export const postActions = [
  { key: 'post', label: '过账', statuses: ['draft'] },
  { key: 'reverse', label: '冲销', statuses: ['posted'], prompt: 'reason' as const, danger: true },
];

