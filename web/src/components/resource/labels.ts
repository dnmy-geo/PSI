import { useQuery } from '@tanstack/react-query';
import type { Row } from '../../api/client';
import { lookupRows } from './lookups';
import type { Lookup, ResourceConfig } from './types';

export function labelOf(row: Row): string {
  const code = row.code ?? row.document_no ?? row.username;
  const name = row.name ?? row.display_name;
  return [code, name].filter(Boolean).join(' · ') || String(row.id ?? '');
}

export function useLabels(config: ResourceConfig) {
  const lineFields = [...(config.lines ?? []), ...(config.detailLines ?? [])].flatMap((group) => group.fields);
  const needed = Array.from(new Set([
    ...config.columns.map((column) => column.lookup),
    ...(config.fields ?? []).map((field) => field.lookup),
    ...lineFields.map((field) => field.lookup),
    // 明细里的 item_id/unit_id 常是 hidden 字段（没有 lookup），但详情仍要按字典翻译成中文。
    ...(lineFields.some((field) => field.name === 'item_id') ? ['items' as Lookup] : []),
    ...(lineFields.some((field) => field.name === 'unit_id') ? ['units' as Lookup] : []),
  ].filter((value): value is Lookup => !!value)));
  const result = useQuery({ queryKey: ['lookup-labels', config.menuCode, needed], queryFn: async () => {
    const entries = await Promise.all(needed.map(async (key) => {
      try { return [key, await lookupRows(key)] as const; }
      catch { return [key, []] as const; }
    }));
    return Object.fromEntries(entries) as Partial<Record<Lookup, Row[]>>;
  }, staleTime: 30_000 });
  const data = result.data;
  return {
    display(value: unknown, lookup?: Lookup): string {
      if (value == null) return '—';
      if (Array.isArray(value)) return value.map((item) => this.display(item, lookup)).join('、');
      if (!lookup) return String(value);
      return labelOf((data?.[lookup] ?? []).find((row) => row.id === value) ?? { id: value });
    },
    refresh: result.refetch,
  };
}

