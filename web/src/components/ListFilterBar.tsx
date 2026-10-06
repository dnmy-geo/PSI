import { useState } from 'react';
import { Button, DatePicker, Input, Select } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';

export type FilterValues = Record<string, string>;
export type FilterField = {
  key: string;
  label: string;
  kind?: 'text' | 'select' | 'dateRange' | 'month';
  options?: { label: string; value: string }[];
};

export function ListFilterBar({ fields, onApply, initialValues = {} }: {
  fields: FilterField[];
  onApply: (values: FilterValues) => void;
  initialValues?: FilterValues;
}) {
  const [draft, setDraft] = useState<FilterValues>(initialValues);
  const update = (key: string, value: string) => setDraft((previous) => ({ ...previous, [key]: value }));
  return <section className="list-filters" aria-label="筛选条件">
    <div className="list-filters-title">筛选条件</div>
    <div className="list-filters-body">
      {fields.map((field) => <label className="list-filter-field" key={field.key}>
        <span>{field.label}</span>
        {field.kind === 'select' ? <Select value={draft[field.key] || undefined} placeholder={`全部${field.label}`}
          allowClear options={field.options} onChange={(value) => update(field.key, value ?? '')} />
          : field.kind === 'month' ? <DatePicker picker="month" value={draft[field.key] ? dayjs(`${draft[field.key]}-01`) : null}
            onChange={(date) => update(field.key, date?.format('YYYY-MM') ?? '')} />
          : field.kind === 'dateRange' ? <DatePicker.RangePicker value={draft[`${field.key}From`] && draft[`${field.key}To`]
            ? [dayjs(draft[`${field.key}From`]), dayjs(draft[`${field.key}To`])] : null}
            onChange={(dates) => setDraft((previous) => ({ ...previous,
              [`${field.key}From`]: dates?.[0]?.format('YYYY-MM-DD') ?? '',
              [`${field.key}To`]: dates?.[1]?.format('YYYY-MM-DD') ?? '',
            }))} />
            : <Input value={draft[field.key] ?? ''} placeholder={`请输入${field.label}`} prefix={<SearchOutlined aria-hidden="true" />} allowClear
              onChange={(event) => update(field.key, event.target.value)} onPressEnter={() => onApply(draft)} />}
      </label>)}
      <div className="list-filter-actions">
        <Button type="primary" onClick={() => onApply(draft)}>查询</Button>
        <Button onClick={() => { setDraft(initialValues); onApply(initialValues); }}>重置</Button>
      </div>
    </div>
  </section>;
}
