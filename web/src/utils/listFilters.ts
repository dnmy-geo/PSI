import { get, type Row } from '../api/client';

export function matchesKeyword(row: Row, keyword: string, fields?: string[]) {
  const query = keyword.trim().toLocaleLowerCase();
  if (!query) return true;
  return (fields ?? Object.keys(row)).some((field) => String(row[field] ?? '').toLocaleLowerCase().includes(query));
}

export function matchesDateRange(value: unknown, from?: string, to?: string) {
  const date = String(value ?? '').slice(0, 10);
  return (!from || date >= from) && (!to || date <= to);
}

export async function getAllPages(path: string, params?: Record<string, string | number | undefined>) {
  const rows: Row[] = [];
  for (let offset = 0; ; offset += 500) {
    const page = await get<Row[]>(path, { ...params, limit: 500, offset });
    rows.push(...page);
    if (page.length < 500) return rows;
  }
}
