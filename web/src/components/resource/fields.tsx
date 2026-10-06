import { useEffect, useRef } from 'react';
import { Form } from 'antd';
import { ProFormDatePicker, ProFormDigit, ProFormSelect, ProFormSwitch, ProFormText, ProFormTextArea } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { get, type Row } from '../../api/client';
import { labelOf } from './labels';
import { lookupRows } from './lookups';
import type { FieldSpec } from './types';

/** 只读的「物料」：显示本行来源行带出的物料（编码 · 名称），避免只看得到订单明细里的编码与数量。 */
function ItemDisplay({ field, rowPathPrefix }: { field: FieldSpec; rowPathPrefix?: (string | number)[] }) {
  const form = Form.useFormInstance();
  const itemId = Form.useWatch([...(rowPathPrefix ?? []), field.itemSource ?? 'item_id'], form);
  const items = useQuery({ queryKey: ['source-items'], queryFn: () => get<Row[]>('/api/items'), retry: false });
  const item = (items.data ?? []).find((row) => row.id === itemId);
  // 只显示名称：这一行有 5 列，编码在「订单明细」列已经能看到，完整「编码 · 名称」留在悬停提示里。
  return <Form.Item label={field.label} style={{ marginBottom: 0 }}>
    {item
      ? <span title={labelOf(item)}>{String(item.name ?? item.code)}</span>
      : <span className="dim">选择订单明细后带出</span>}
  </Form.Item>;
}

/** 只读的「单位」：显示本行物料的基本单位编码。数量按基本单位计的单据（如生产计划产出）用它标注。 */
function UnitDisplay({ field, rowPathPrefix }: { field: FieldSpec; rowPathPrefix?: (string | number)[] }) {
  const form = Form.useFormInstance();
  const itemId = Form.useWatch([...(rowPathPrefix ?? []), field.itemSource ?? 'item_id'], form);
  const items = useQuery({ queryKey: ['source-items'], queryFn: () => get<Row[]>('/api/items'), retry: false });
  const units = useQuery({ queryKey: ['lookup-units'], queryFn: () => lookupRows('units'), staleTime: 60_000 });
  const item = (items.data ?? []).find((row) => row.id === itemId);
  const unit = (units.data ?? []).find((row) => row.id === item?.base_unit_id);
  return <Form.Item label={field.label} style={{ marginBottom: 0 }}>
    {item
      ? <span title={unit ? labelOf(unit) : undefined}>{unit ? String(unit.code) : '—'}</span>
      : <span className="dim">选择物料后带出</span>}
  </Form.Item>;
}

/** 只读的「可用库存」：按单据上的仓库 + 本行物料显示当前基本单位结存。 */
function StockHint({ field, rowPathPrefix }: { field: FieldSpec; rowPathPrefix?: (string | number)[] }) {
  const form = Form.useFormInstance();
  const itemId = Form.useWatch([...(rowPathPrefix ?? []), field.stockItem ?? 'item_id'], form);
  const warehouseId = Form.useWatch(field.stockWarehouse ?? 'warehouse_id', form);
  const balances = useQuery({ queryKey: ['stock-balances'], enabled: !!itemId && !!warehouseId,
    staleTime: 10_000, queryFn: () => get<Row[]>('/api/inventory/balances') });
  const items = useQuery({ queryKey: ['source-items'], queryFn: () => get<Row[]>('/api/items'), retry: false });
  const units = useQuery({ queryKey: ['lookup-units'], queryFn: () => lookupRows('units'), staleTime: 60_000 });
  const label = <Form.Item label={field.label} style={{ marginBottom: 0 }}>
    {!itemId || !warehouseId
      ? <span className="dim">选择物料与仓库后显示</span>
      : !balances.data
        ? <span className="dim">读取中…</span>
        : <span className="psi-stock-hint">
          {Number((balances.data.find((row) => row.item_id === itemId && row.warehouse_id === warehouseId)?.quantity_base) ?? 0)
            .toLocaleString('zh-CN', { maximumFractionDigits: 6 })}
          {' '}
          {String((units.data ?? []).find((unit) => unit.id === (items.data ?? []).find((item) => item.id === itemId)?.base_unit_id)?.code ?? '')}
        </span>}
  </Form.Item>;
  return label;
}

/** 来源行（订单行/出库行/领料行…）的统一文案：物料编码 · 数量。 */
function sourceLineLabel(row: Row, items: Row[] | undefined): string {
  const code = items?.find((item) => item.id === row.item_id)?.code ?? row.item_id;
  const quantity = row.quantity ?? row.quantity_base ?? row.expected_quantity_base ?? row.planned_quantity_base ?? '';
  return `${String(code)} · ${String(quantity)}`;
}

export /** 详情里把「来源行」外键显示成 物料·数量，而不是裸 UUID；取不到（无权限/来源已删）时退回原值。 */
function SourceLineCell({ field, parentId, lineId }: { field: FieldSpec; parentId: unknown; lineId: unknown }) {
  const source = useQuery({ queryKey: ['source-line', field.source?.endpoint, parentId],
    queryFn: () => get<Row>(`${field.source!.endpoint}/${parentId}`), enabled: !!parentId && !!field.source });
  const items = useQuery({ queryKey: ['source-items'], queryFn: () => get<Row[]>('/api/items'), retry: false });
  const rows = (source.data?.[field.source?.lineKey ?? 'lines'] ?? []) as Row[];
  const line = rows.find((entry) => String(entry.id) === String(lineId));
  if (!line) return <span className="mono dim">{String(lineId ?? '—')}</span>;
  return <span>{sourceLineLabel(line, items.data)}</span>;
}

export function Field({ field, editing, row, setCurrentRowData, rowPathPrefix }: {
  field: FieldSpec; editing: boolean; row?: Row | null;
  setCurrentRowData?: (values: Row) => void;
  /** 明细行在表单里的路径前缀（如 ['lines', 0]）：行内字段用相对名 useWatch 取不到值。 */
  rowPathPrefix?: (string | number)[];
}) {
  const parentId = Form.useWatch(field.source?.parent ?? '__unused__');
  const condition = Form.useWatch(field.showWhen?.name ?? '__unused_condition__');
  const companion = Form.useWatch(field.requiredWhenFilled ?? '__unused_companion__');
  const itemForUnit = Form.useWatch(field.unitFor
    ? (rowPathPrefix ? [...rowPathPrefix, field.unitFor] : field.unitFor) : '__unused_unit_for__');
  const form = Form.useFormInstance();
  const companionFilled = companion !== undefined && companion !== null && companion !== '';
  // requiredWhenFilled 的字段与同伴同生共死：同伴为空时本字段既置灰也清空。
  // 否则用户清掉「基本单位」后会留下「有数量没单位」的组合，被后端的成对校验拒绝。
  const orphaned = !!field.requiredWhenFilled && !companionFilled;
  // 只在同伴「由有变无」时清空。若只判空，首次渲染时 initialValues 还没进表单，
  // 同伴看起来是空的，会把编辑态已经填好的值抹掉且再也回不来。
  const companionWasFilled = useRef(companionFilled);
  useEffect(() => {
    if (companionWasFilled.current && orphaned) form.setFieldValue(field.name, undefined);
    companionWasFilled.current = companionFilled;
  }, [companionFilled, orphaned, field.name, form]);
  const source = useQuery({ queryKey: ['source-line', field.source?.endpoint, parentId],
    queryFn: () => get<Row>(`${field.source!.endpoint}/${parentId}`), enabled: field.kind === 'sourceLine' && !!parentId });
  const sourceItems = useQuery({ queryKey: ['source-items'], queryFn: () => get<Row[]>('/api/items'), enabled: field.kind === 'sourceLine' });
  if (editing && field.hiddenOnEdit) return null;
  if (field.showWhen && condition !== field.showWhen.equals) return null;
  const blockedValue = field.disabledWhenFilled ? row?.[field.disabledWhenFilled] : undefined;
  const blockedByRow = Array.isArray(blockedValue) && blockedValue.length > 0;
  const disabledOnEdit = editing && field.readOnlyOnEdit;
  const common = { name: field.name, label: field.label,
    // 编辑时置灰的字段不能再要求必填，否则空值永远过不了校验。
    rules: disabledOnEdit ? [] : [
      ...(field.required || (editing && field.requiredOnEdit) || (!!field.requiredWhenFilled && companionFilled)
        ? [{ required: true, message: `请填写${field.label}` }] : []),
      ...(field.minLength ? [{ min: field.minLength, message: `${field.label}至少 ${field.minLength} 位` }] : []),
    ],
    // orphaned：同伴没选，填了也没意义，直接禁用。
    // disabledWhenFilled 读的是接口返回的只读字段（如 related_units），它不在表单声明里，
    // 走 initialValues 拿不到，所以直接看编辑行的原始数据。
    disabled: orphaned || (editing && field.readOnlyOnEdit) || blockedByRow };
  switch (field.kind) {
    case 'hidden': return <Form.Item name={field.name} hidden><input /></Form.Item>;
    case 'stock': return <StockHint field={field} rowPathPrefix={rowPathPrefix} />;
    case 'item': return <ItemDisplay field={field} rowPathPrefix={rowPathPrefix} />;
    case 'unit': return <UnitDisplay field={field} rowPathPrefix={rowPathPrefix} />;
    case 'sourceLine': {
      const rows = (source.data?.[field.source?.lineKey ?? 'lines'] ?? []) as Row[];
      return <ProFormSelect {...common} disabled={!parentId} options={rows.map((row) => ({
        value: String(row.id), label: sourceLineLabel(row, sourceItems.data),
      }))} fieldProps={{ onChange: (value) => {
        const selected = rows.find((row) => row.id === value);
        if (selected) setCurrentRowData?.({ item_id: selected.item_id, unit_id: selected.unit_id });
      } }} />;
    }
    case 'date': return <ProFormDatePicker {...common} fieldProps={{ format: 'YYYY-MM-DD' }} />;
    case 'number': return <ProFormDigit {...common} fieldProps={{ precision: 6, min: field.min ?? 0, placeholder: field.placeholder }} />;
    case 'integer': return <ProFormDigit {...common} fieldProps={{ precision: 0, min: 0, placeholder: field.placeholder }} />;
    case 'switch': return <ProFormSwitch {...common} />;
    case 'password': return <ProFormText.Password {...common}
      placeholder={disabledOnEdit ? (field.readOnlyPlaceholder ?? field.placeholder) : field.placeholder} />;
    case 'textarea': return <ProFormTextArea {...common} />;
    case 'select': return <ProFormSelect {...common} options={field.choices} />;
    case 'lookup':
    case 'multiLookup': return <ProFormSelect {...common} mode={field.kind === 'multiLookup' ? 'multiple' : undefined}
      showSearch fieldProps={{ optionFilterProp: 'label' }}
      // params 变化会重新拉取选项：选了物料后，单位列表只留该物料能换算的单位。
      params={field.unitFor ? { item: itemForUnit } : undefined}
      request={async (params) => {
        const rows = await lookupRows(field.lookup!);
        let allowed = rows;
        if (field.unitFor) {
          const item = (await lookupRows('items')).find((entry) => entry.id === (params as Row | undefined)?.item);
          const baseUnitId = item?.base_unit_id;
          if (baseUnitId) allowed = rows.filter((unit) => unit.id === baseUnitId || unit.base_unit_id === baseUnitId);
        }
        return allowed.filter((row) =>
          (!field.partyType || (Array.isArray(row.types) && row.types.includes(field.partyType))) &&
          (!field.topLevelOnly || !row.parent_id) &&
          (!field.filter || field.filter(row))
        ).map((row) => ({ label: labelOf(row), value: String(row.id) }));
      }} />;
    default: return <ProFormText {...common} placeholder={editing && field.requiredOnEdit ? undefined : field.placeholder} />;
  }
}

