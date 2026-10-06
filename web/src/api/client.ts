export type Row = Record<string, unknown>;
export type Session = {
  user_id: string;
  organization_id: string;
  username: string;
  display_name: string;
  csrf_token: string;
};

let csrfToken = '';
export function setCsrfToken(token: string) { csrfToken = token; }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** Pydantic 自带校验消息是英文的，按错误类型归一到中文。 */
const VALIDATION_MESSAGES: Record<string, string> = {
  missing: '必填项没有填写',
  string_too_short: '内容太短',
  string_too_long: '内容太长',
  string_type: '必须是文本',
  string_pattern_mismatch: '格式不正确',
  int_parsing: '必须是整数',
  int_type: '必须是整数',
  float_parsing: '必须是数字',
  float_type: '必须是数字',
  decimal_parsing: '必须是数字',
  bool_parsing: '必须是开关值',
  uuid_parsing: '格式不正确',
  date_parsing: '日期格式不正确',
  datetime_parsing: '时间格式不正确',
  enum: '选项不在允许范围内',
  literal_error: '选项不在允许范围内',
  list_type: '必须是列表',
  too_short: '至少要有一条',
  too_long: '条数超出上限',
  greater_than: '数值太小',
  greater_than_equal: '数值太小',
  less_than: '数值太大',
  less_than_equal: '数值太大',
  value_error: '内容不合法',
  json_invalid: '请求格式不正确',
};

function validationMessage(entry: unknown): string {
  if (typeof entry !== 'object' || entry === null) return String(entry);
  const record = entry as { msg?: unknown; type?: unknown; loc?: unknown };
  const raw = String(record.msg ?? '');
  // 后端自己 raise 的 ValueError 会被 Pydantic 加上 "Value error, " 前缀，去掉后就是写好的中文。
  const stripped = raw.replace(/^Value error,\s*/, '');
  if (/[一-龥]/.test(stripped)) return stripped;
  const field = Array.isArray(record.loc) ? record.loc.filter((part) => typeof part === 'string').at(-1) : undefined;
  const mapped = VALIDATION_MESSAGES[String(record.type ?? '')] ?? '内容不合法';
  return field ? `${String(field)}：${mapped}` : mapped;
}

function detailMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(validationMessage).join('；');
  return '请求失败';
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (init.method && !['GET', 'HEAD'].includes(init.method.toUpperCase()) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, credentials: 'same-origin' });
  } catch {
    throw new ApiError(0, '网络连接失败，请检查后端服务');
  }
  if (!response.ok) {
    let detail: unknown;
    try { detail = (await response.json()).detail; } catch { /* empty response */ }
    throw new ApiError(response.status, detailMessage(detail));
  }
  return response;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await send(path, init);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function withQuery(path: string, params?: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  return path + (query.size ? `?${query}` : '');
}

export function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  return request<T>(withQuery(path, params));
}

/** 分页 GET：正文之外读取后端给出的精确总数（X-Total-Count）；缺失时为 NaN，调用方据此回退。 */
export async function getPage<T>(path: string, params?: Record<string, string | number | undefined>): Promise<{ data: T; total: number }> {
  const response = await send(withQuery(path, params));
  const header = response.headers.get('X-Total-Count');
  return { data: (await response.json()) as T, total: header === null ? Number.NaN : Number(header) };
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
}

export function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'PUT', body: JSON.stringify(body) });
}

export function remove(path: string): Promise<void> {
  return request<void>(path, { method: 'DELETE' });
}

export function upload<T>(path: string, data: FormData): Promise<T> {
  return request<T>(path, { method: 'POST', body: data });
}
