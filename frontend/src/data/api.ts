import { mockLines } from './mock';
import type {
  ApprovalOptions, ApprovalResult, CalculationRequest, ExportFilters, OrderLine,
  OrderRun, StockRecord, Urgency,
} from './types';

const configuredBase = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '');
const useDevProxy = import.meta.env.DEV && import.meta.env.VITE_API_PROXY !== 'false';
const base = configuredBase && !useDevProxy ? configuredBase : '';
export const isMock = !configuredBase;
const piiTextPattern = /(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:customer|client|клиент|заказчик|телефон|почта|e-mail|email|фио|контактные данные)\b)/i;
const phonePattern = /(?:\+?\d[\d ()-]{7,}\d)/;
const exportHeaders = ['SupplierCode', 'SKU', 'Quantity', 'Warehouse'];
let mockRunId = 'synthetic-demo-run';
let mockRunCreatedAt = new Date().toISOString();

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

async function errorFromResponse(response: Response, path: string): Promise<ApiError> {
  let detail = '';
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === 'object' && 'detail' in payload && typeof payload.detail === 'string') {
      detail = payload.detail;
    }
  } catch {
    // Some proxies return an empty or non-JSON error body; status remains useful context.
  }
  return new ApiError(detail || `Backend вернул ${response.status} для ${path}`, response.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 20000);
  try {
    const isMultipart = init?.body instanceof FormData;
    const headers = isMultipart
      ? init?.headers
      : { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers };
    const response = await fetch(`${base}${path}`, { ...init, headers, signal: controller.signal });
    if (!response.ok) throw await errorFromResponse(response, path);
    if (response.status === 204) return undefined as T;
    const body = await response.text();
    if (!body) return undefined as T;
    if (!response.headers.get('content-type')?.toLowerCase().includes('application/json')) return body as T;
    try {
      return JSON.parse(body) as T;
    } catch {
      throw new ApiError(`Backend вернул некорректный JSON для ${path}.`, response.status);
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError('Backend не ответил за 20 секунд. Проверьте соединение и повторите запрос.');
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function requiredString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== 'string') throw new ApiError(`В ответе backend отсутствует строковое поле ${key}.`);
  return value;
}

function optionalString(record: Record<string, unknown>, key: string): string | undefined {
  const value = record[key];
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value !== 'string') throw new ApiError(`Некорректное строковое поле ${key} в ответе backend.`);
  return value;
}

function requiredNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new ApiError(`Некорректное числовое поле ${key} в ответе backend.`);
  return value;
}

function toOrderLine(value: unknown): OrderLine {
  if (!value || typeof value !== 'object') throw new ApiError('Некорректная строка заказа в ответе backend.');
  const record = value as Record<string, unknown>;
  const id = requiredString(record, 'id');
  const sku = requiredString(record, 'sku');
  const product = requiredString(record, 'product_name');
  const category = requiredString(record, 'category');
  const warehouse = requiredString(record, 'warehouse');
  const unit = requiredString(record, 'unit');
  const supplierCode = optionalString(record, 'supplier_code') ?? '';
  const supplier = optionalString(record, 'supplier_name') ?? supplierCode;
  const rawUrgency = requiredString(record, 'urgency');
  const urgencyMap: Record<string, Urgency> = { high: 'critical', normal: 'planned', critical: 'critical', soon: 'soon', planned: 'planned' };
  const urgency = urgencyMap[rawUrgency];
  if (!urgency) throw new ApiError(`Некорректный уровень срочности: ${rawUrgency}.`);
  const rawJustification = record.justification;
  const justification = Array.isArray(rawJustification)
    ? rawJustification.map((item) => {
      if (typeof item !== 'string') throw new ApiError('Некорректное пояснение в ответе backend.');
      return item;
    }).join(' ')
    : typeof rawJustification === 'string' ? rawJustification : '';
  const allText = [id, sku, product, category, warehouse, supplierCode, supplier, unit, justification];
  if (allText.some((text) => piiTextPattern.test(text)) || [product, supplier, justification].some((text) => phonePattern.test(text))) {
    throw new ApiError('Backend вернул поле с возможными персональными данными. Строка скрыта; проверьте API контракт.');
  }
  const quantity = requiredNumber(record, 'quantity');
  const forecast = requiredNumber(record, 'forecast_monthly_demand');
  const status = record.status === 'approved' ? 'approved' : 'pending';
  return {
    id, sku, product, category, warehouse, unit, supplierCode, supplier,
    quantity, recommendedQty: quantity, urgency,
    monthlyUse: forecast,
    bomId: optionalString(record, 'bomId'),
    justification,
    stock: undefined,
    status,
    reviewed: status === 'approved',
    approvedBy: optionalString(record, 'approved_by'),
    approvedAt: optionalString(record, 'approved_at') ?? optionalString(record, 'approval_timestamp'),
    managerNote: optionalString(record, 'manager_note'),
  };
}

function parseOrderRun(payload: unknown): OrderRun {
  if (!payload || typeof payload !== 'object') throw new ApiError('Некорректный ответ latest calculation от backend.');
  const record = payload as Record<string, unknown>;
  let items: unknown[];
  if (Array.isArray(record.orders)) {
    items = record.orders;
  } else if (Array.isArray(record.suppliers)) {
    items = record.suppliers.flatMap((supplier) => {
      if (!supplier || typeof supplier !== 'object') throw new ApiError('Некорректная группа поставщика в /api/orders.');
      const supplierRecord = supplier as Record<string, unknown>;
      const nested = supplierRecord.items;
      if (!Array.isArray(nested)) throw new ApiError('Ожидался массив items в группе поставщика.');
      return nested.map((item) => {
        if (!item || typeof item !== 'object') return item;
        const itemRecord = item as Record<string, unknown>;
        return {
          supplier_code: supplierRecord.supplier_code,
          supplier_name: supplierRecord.supplier_name,
          ...itemRecord,
        };
      });
    });
  } else {
    throw new ApiError('Ожидался массив orders или suppliers в ответе /api/orders.');
  }
  const runId = typeof record.run_id === 'string' ? record.run_id : null;
  const createdAt = typeof record.created_at === 'string' ? record.created_at : undefined;
  return { runId, createdAt, lines: items.map(toOrderLine) };
}

export async function checkHealth(): Promise<boolean> {
  if (isMock) return true;
  const payload = await request<unknown>('/api/health');
  if (!payload || typeof payload !== 'object' || !('status' in payload) || payload.status !== 'ok') {
    throw new ApiError('Backend ответил, но health status не равен ok.');
  }
  return true;
}

export async function getOrders(): Promise<OrderRun> {
  if (isMock) return { runId: mockRunId, createdAt: mockRunCreatedAt, lines: mockLines.map((line) => ({ ...line })) };
  return parseOrderRun(await request<unknown>('/api/orders'));
}

export async function calculate(scope: CalculationRequest): Promise<OrderRun> {
  if (isMock) {
    await new Promise((resolve) => window.setTimeout(resolve, 400));
    mockRunId = `synthetic-demo-${Date.now()}`;
    mockRunCreatedAt = new Date().toISOString();
    return {
      runId: mockRunId,
      createdAt: mockRunCreatedAt,
      lines: mockLines.filter((line) => (!scope.warehouse || line.warehouse === scope.warehouse)
        && (!scope.category || line.category === scope.category)).map((line) => ({ ...line, reviewed: false, status: 'pending' })),
    };
  }
  const query = new URLSearchParams();
  if (scope.warehouse) query.set('warehouse', scope.warehouse);
  if (scope.category) query.set('category', scope.category);
  const suffix = query.size ? `?${query.toString()}` : '';
  return parseOrderRun(await request<unknown>(`/api/calculate${suffix}`, { method: 'POST' }));
}

export async function getStock(warehouse?: string): Promise<StockRecord[]> {
  if (isMock) {
    return mockLines.filter((line) => !warehouse || line.warehouse === warehouse).map((line) => ({
      sku: line.sku, warehouse: line.warehouse, quantity: line.stock ?? 0, stockout: line.stockout ?? false,
    }));
  }
  const query = warehouse ? `?${new URLSearchParams({ warehouse })}` : '';
  const payload = await request<unknown>(`/api/stock${query}`);
  if (!payload || typeof payload !== 'object' || !('items' in payload) || !Array.isArray(payload.items)) {
    throw new ApiError('Ожидался массив items в ответе /api/stock.');
  }
  return payload.items.map((value): StockRecord => {
    if (!value || typeof value !== 'object') throw new ApiError('Некорректная запись склада в /api/stock.');
    const record = value as Record<string, unknown>;
    const sku = requiredString(record, 'sku');
    const itemWarehouse = requiredString(record, 'warehouse');
    const quantity = requiredNumber(record, 'quantity');
    if ([sku, itemWarehouse].some((text) => piiTextPattern.test(text)) || phonePattern.test(itemWarehouse)) {
      throw new ApiError('Backend вернул складскую запись с возможными персональными данными; запись скрыта.');
    }
    if (typeof record.stockout !== 'boolean') throw new ApiError('Некорректное поле stockout в ответе /api/stock.');
    return { sku, warehouse: itemWarehouse, quantity, stockout: record.stockout };
  });
}

export function mergeStock(lines: OrderLine[], stock: StockRecord[]): OrderLine[] {
  const lookup = new Map(stock.map((record) => [`${record.sku}\u0000${record.warehouse}`, record]));
  return lines.map((line) => {
    const record = lookup.get(`${line.sku}\u0000${line.warehouse}`);
    return record ? { ...line, stock: record.quantity, stockout: record.stockout } : line;
  });
}

export async function approveOrders(lines: OrderLine[], options: ApprovalOptions = {}): Promise<ApprovalResult> {
  const targets = lines.filter((line) => line.status !== 'approved');
  if (!targets.length || targets.some((line) => !line.reviewed || !Number.isFinite(line.quantity) || line.quantity < 0)) {
    throw new ApiError('Проверьте выбранные позиции и количества перед подтверждением.');
  }
  if (targets.some((line) => line.quantity !== line.recommendedQty)) {
    throw new ApiError('Текущий API не принимает изменённое количество. Верните расчётное значение перед согласованием.');
  }
  if (options.managerNote && options.managerNote.length > 1000) throw new ApiError('Заметка менеджера не должна превышать 1 000 символов.');
  if (options.managerNote && (piiTextPattern.test(options.managerNote) || phonePattern.test(options.managerNote))) {
    throw new ApiError('Заметка содержит возможные персональные данные; удалите их перед отправкой.');
  }
  if (isMock) {
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    return { approved: targets.map((line) => line.id), alreadyApproved: [], approvedBy: options.approvedBy || 'manager' };
  }
  const body: Record<string, unknown> = {
    item_ids: targets.map((line) => line.id),
    confirmed: true,
    approved_by: options.approvedBy?.trim() || 'manager',
    manager_note: options.managerNote?.trim() || '',
  };
  const payload = await request<unknown>('/api/orders/approve', { method: 'POST', body: JSON.stringify(body) });
  if (!payload || typeof payload !== 'object') throw new ApiError('Некорректный ответ /api/orders/approve.');
  const result = payload as Record<string, unknown>;
  if (!Array.isArray(result.approved) || !Array.isArray(result.already_approved)) {
    throw new ApiError('Ответ /api/orders/approve не содержит approved и already_approved.');
  }
  return {
    approved: result.approved.filter((id): id is string => typeof id === 'string'),
    alreadyApproved: result.already_approved.filter((id): id is string => typeof id === 'string'),
    approvalTimestamp: typeof result.approval_timestamp === 'string' ? result.approval_timestamp : undefined,
    approvedBy: typeof result.approved_by === 'string' ? result.approved_by : options.approvedBy,
  };
}

function parseCsv(source: string): string[][] {
  const firstLine = source.replace(/^\uFEFF/, '').split(/\r?\n/, 1)[0] ?? '';
  const commas = (firstLine.match(/,/g) ?? []).length;
  const semicolons = (firstLine.match(/;/g) ?? []).length;
  const delimiter = semicolons > commas ? ';' : ',';
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  const csv = source.replace(/^\uFEFF/, '');
  for (let index = 0; index < csv.length; index += 1) {
    const char = csv[index];
    if (quoted) {
      if (char === '"' && csv[index + 1] === '"') { cell += '"'; index += 1; }
      else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"' && cell.length === 0) quoted = true;
    else if (char === delimiter) { row.push(cell); cell = ''; }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && csv[index + 1] === '\n') index += 1;
      row.push(cell); cell = '';
      if (row.some((value) => value.length > 0)) rows.push(row);
      row = [];
    } else cell += char;
  }
  if (quoted) throw new ApiError('CSV экспорта имеет незакрытое поле в кавычках.');
  if (cell.length || row.length) { row.push(cell); if (row.some((value) => value.length > 0)) rows.push(row); }
  return rows;
}

function filenameFromResponse(response: Response): string {
  const disposition = response.headers.get('content-disposition') ?? '';
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try { return decodeURIComponent(encoded); } catch { /* Use the normal filename fallback below. */ }
  }
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  return plain || 'approved_orders_1c.csv';
}

export async function exportOrders(filters: ExportFilters = {}): Promise<{ blob: Blob; filename: string }> {
  if (isMock) throw new ApiError('Экспорт 1С доступен после подключения backend через VITE_API_BASE_URL.');
  const query = new URLSearchParams();
  if (filters.date) query.set('date', filters.date);
  if (filters.supplierCode) query.set('supplier_code', filters.supplierCode);
  if (filters.warehouse) query.set('warehouse', filters.warehouse);
  const suffix = query.size ? `?${query.toString()}` : '';
  const path = `/api/orders/export-1c${suffix}`;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(`${base}${path}`, { signal: controller.signal, headers: { Accept: 'text/csv' } });
    if (!response.ok) throw await errorFromResponse(response, path);
    const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
    if (!/(?:text\/csv|application\/csv|application\/vnd\.ms-excel)/.test(contentType)) {
      throw new ApiError('Backend вернул неожиданный формат экспорта; CSV не скачан.');
    }
    const csv = await response.text();
    const rows = parseCsv(csv);
    if (!rows.length || rows[0].length !== exportHeaders.length || exportHeaders.some((header, index) => rows[0][index] !== header)) {
      throw new ApiError('Экспорт остановлен: формат колонок не совпадает с контрактом 1С.');
    }
    for (const row of rows.slice(1)) {
      if (row.length !== exportHeaders.length) throw new ApiError('Экспорт остановлен: некорректное число полей в строке.');
      if (row.some((value) => piiTextPattern.test(value)) || [row[0], row[3]].some((value) => phonePattern.test(value))) {
        throw new ApiError('Экспорт остановлен: обнаружены возможные персональные данные. Проверьте выгрузку на backend.');
      }
    }
    return { blob: new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8' }), filename: filenameFromResponse(response) };
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw new ApiError('Backend не ответил за 30 секунд. Проверьте соединение и повторите запрос.');
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export async function uploadReport(file: File): Promise<void> {
  if (isMock) throw new ApiError('Загрузка отчётов доступна после подключения backend через VITE_API_BASE_URL.');
  if (!/\.xlsx$/i.test(file.name)) throw new ApiError('Backend принимает только книгу Excel в формате .xlsx.');
  if (file.size > 25 * 1024 * 1024) throw new ApiError('Размер файла превышает лимит 25 MiB.');
  const body = new FormData();
  body.append('file', file);
  await request<void>('/api/upload', { method: 'POST', body });
}
