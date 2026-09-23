import { mockLines } from './mock';
import type { CalculationRequest, CalculationResponse, OrderLine, Urgency } from './types';

const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '');
export const isMock = !base;
const piiTextPattern = /(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:customer|client|клиент|заказчик|телефон|почта|e-mail|email|фио|контактные данные)\b)/i;
const phonePattern = /(?:\+?\d[\d ()-]{7,}\d)/;
const exportHeaders = ['SKU', 'BOM_ID', 'WAREHOUSE', 'SUPPLIER', 'QUANTITY', 'UNIT'];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 15000);
  try {
    const isMultipart = init?.body instanceof FormData;
    const response = await fetch(`${base}${path}`, {
      ...init,
      signal: controller.signal,
      headers: isMultipart ? init?.headers : { 'Content-Type': 'application/json', ...init?.headers }
    });
    if (!response.ok) throw new Error(`Backend вернул ${response.status} для ${path}`);
    if (response.status === 204) return undefined as T;
    return await response.json() as T;
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw new Error('Backend не ответил за 15 секунд. Проверьте соединение и повторите запрос.');
    throw error;
  } finally { window.clearTimeout(timer); }
}

async function requestAction(path: string, init: RequestInit): Promise<void> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(`${base}${path}`, { ...init, signal: controller.signal });
    if (!response.ok) throw new Error(`Backend вернул ${response.status} для ${path}`);
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw new Error('Backend не ответил за 30 секунд. Проверьте соединение и повторите запрос.');
    throw error;
  } finally { window.clearTimeout(timer); }
}

function safeLine(value: unknown, allowApprovedStatus = false): OrderLine {
  if (!value || typeof value !== 'object') throw new Error('Некорректная строка заказа в ответе backend.');
  const v = value as Record<string, unknown>;
  const str = (key: string) => { if (typeof v[key] !== 'string') throw new Error(`В ответе backend отсутствует поле ${key}.`); return v[key] as string; };
  const num = (key: string) => { if (typeof v[key] !== 'number' || !Number.isFinite(v[key])) throw new Error(`Некорректное числовое поле ${key}.`); return v[key] as number; };
  const urgency = str('urgency');
  if (!['critical', 'soon', 'planned'].includes(urgency)) throw new Error('Некорректный уровень срочности.');
  const fields = ['id', 'sku', 'bomId', 'product', 'category', 'supplier', 'warehouse', 'unit', 'justification'].map(str);
  const seasonality = v.seasonality === undefined ? undefined : typeof v.seasonality === 'string' ? v.seasonality : (() => { throw new Error('Некорректное поле seasonality в ответе backend.'); })();
  const moq = v.moq === undefined ? undefined : typeof v.moq === 'number' && Number.isFinite(v.moq) && v.moq >= 0 ? v.moq : (() => { throw new Error('Некорректное поле moq в ответе backend.'); })();
  if ([...fields, ...(seasonality ? [seasonality] : [])].some(text => piiTextPattern.test(text)) || [fields[3], fields[5], fields[6], fields[8], ...(seasonality ? [seasonality] : [])].some(text => phonePattern.test(text))) {
    throw new Error('Backend вернул поле с возможными персональными данными. Строка скрыта; проверьте API контракт.');
  }
  const [id, sku, bomId, product, category, supplier, warehouse, unit, justification] = fields;
  const status = allowApprovedStatus && v.status === 'approved' ? 'approved' : 'pending';
  return { id, sku, bomId, product, category, supplier, warehouse, unit, justification,
    recommendedQty: num('recommendedQty'), quantity: num('recommendedQty'), urgency: urgency as Urgency,
    stock: num('stock'), monthlyUse: num('monthlyUse'), leadDays: num('leadDays'), seasonality, moq, status, reviewed: status === 'approved' };
}

export async function getOrders(): Promise<OrderLine[]> {
  if (isMock) return mockLines.map(line => ({ ...line }));
  const payload = await request<{ lines: unknown[] }>('/api/orders');
  if (!Array.isArray(payload.lines)) throw new Error('Ожидался массив lines в /api/orders.');
  return payload.lines.map(line => safeLine(line, true));
}

export async function calculate(scope: CalculationRequest): Promise<OrderLine[]> {
  if (isMock) {
    await new Promise(resolve => setTimeout(resolve, 400));
    return mockLines.filter(line => (!scope.warehouse || line.warehouse === scope.warehouse) && (!scope.category || line.category === scope.category)).map(line => ({ ...line }));
  }
  const response = await request<CalculationResponse>('/api/calculate', { method: 'POST', body: JSON.stringify(scope) });
  if (!response || !Array.isArray(response.lines)) throw new Error('Ожидался массив lines в ответе /api/calculate.');
  return response.lines.map(line => safeLine(line));
}

export async function approveOrders(lines: OrderLine[]): Promise<void> {
  if (!lines.length || lines.some(line => !line.reviewed || !Number.isFinite(line.quantity) || line.quantity < 0)) {
    throw new Error('Проверьте все позиции и количества перед подтверждением.');
  }
  if (isMock) { await new Promise(resolve => setTimeout(resolve, 350)); return; }
  await requestAction('/api/orders/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lines: lines.map(({ id, quantity }) => ({ id, quantity })) })
  });
}

function parseCsv(source: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = '', quoted = false;
  const csv = source.replace(/^\uFEFF/, '');
  for (let i = 0; i < csv.length; i++) {
    const char = csv[i];
    if (quoted) {
      if (char === '"' && csv[i + 1] === '"') { cell += '"'; i++; }
      else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"' && cell.length === 0) quoted = true;
    else if (char === ';') { row.push(cell); cell = ''; }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && csv[i + 1] === '\n') i++;
      row.push(cell); cell = '';
      if (row.some(value => value.length > 0)) rows.push(row);
      row = [];
    } else cell += char;
  }
  if (quoted) throw new Error('CSV экспорта имеет незакрытое поле в кавычках.');
  if (cell.length || row.length) { row.push(cell); if (row.some(value => value.length > 0)) rows.push(row); }
  return rows;
}

function quoteCsv(value: string) { return `"${value.replace(/"/g, '""')}"`; }
function validateExport(source: string): Blob {
  const rows = parseCsv(source);
  if (!rows.length || rows[0].length !== exportHeaders.length || exportHeaders.some((header, index) => rows[0][index] !== header)) {
    throw new Error('Экспорт остановлен: формат колонок не совпадает с 1С. Проверьте выгрузку на backend.');
  }
  for (const row of rows.slice(1)) {
    if (row.length !== exportHeaders.length) throw new Error('Экспорт остановлен: некорректное число полей в строке.');
    if (row.some(value => piiTextPattern.test(value)) || [row[2], row[3]].some(value => phonePattern.test(value))) {
      throw new Error('Экспорт остановлен: обнаружены возможные персональные данные. Проверьте выгрузку на backend.');
    }
  }
  return new Blob(['\uFEFF', rows.map(row => row.map(quoteCsv).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
}

export async function exportOrders(): Promise<Blob> {
  if (isMock) throw new Error('Экспорт 1С доступен после подключения backend через VITE_API_BASE_URL.');
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(`${base}/api/orders/export-1c`, { signal: controller.signal, headers: { Accept: 'text/csv' } });
    if (!response.ok) throw new Error(`Backend вернул ${response.status} для /api/orders/export-1c`);
    const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
    if (!/(?:text\/csv|application\/csv|application\/vnd\.ms-excel)/.test(contentType)) throw new Error('Backend вернул неожиданный формат экспорта; CSV не скачан.');
    return validateExport(await response.text());
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw new Error('Backend не ответил за 30 секунд. Проверьте соединение и повторите запрос.');
    throw error;
  } finally { window.clearTimeout(timer); }
}

export async function uploadReport(file: File): Promise<void> {
  if (isMock) throw new Error('Загрузка отчётов доступна после подключения backend через VITE_API_BASE_URL.');
  if (!/\.(xlsx|xls|csv)$/i.test(file.name)) throw new Error('Поддерживаются файлы XLSX, XLS и CSV.');
  if (file.size > 25 * 1024 * 1024) throw new Error('Размер файла превышает лимит 25 МБ.');
  const body = new FormData();
  body.append('file', file);
  await requestAction('/api/upload', { method: 'POST', body });
}
