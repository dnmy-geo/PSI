/**
 * 配置化页面引擎的公开入口。
 * 页面作者只需要 ResourceConfig（页面配置契约）与 ResourcePage（渲染器）。
 */
export { ResourcePage } from './ResourcePage';
export { labelOf } from './labels';
export { APPROVAL_TASK_STATUS, FIELD_LABELS, HIDDEN_DETAIL_FIELDS } from './constants';
export type { ActionSpec, FieldSpec, Lookup, ResourceConfig } from './types';
