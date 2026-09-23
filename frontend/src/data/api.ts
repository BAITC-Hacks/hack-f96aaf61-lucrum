import { mockLines } from './mock';
import type { CalculationRequest, CalculationResponse, OrderLine, Urgency } from './types';

const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '');
export const isMock = !base;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(`${base}${path}`, { ...init, signal: controller.signal, headers: { 'Content-Type':'application/json', ...init?.headers } });
    if (!response.ok) throw new Error(`Backend вернул ${response.status} для ${path}`);
    return await response.json() as T;
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw new Error('Backend не ответил за 15 секунд. Проверьте соединение и повторите запрос.');
    throw error;
  } finally { window.clearTimeout(timer); }
}

// Strict allow-list: arbitrary response fields (including possible PII) are never rendered,
// logged, persisted, or exported. Backend must return these documented fields only.
function safeLine(value: unknown): OrderLine {
  if (!value || typeof value !== 'object') throw new Error('Некорректная строка заказа в ответе backend.');
  const v = value as Record<string, unknown>;
  const str = (key: string) => { if (typeof v[key] !== 'string') throw new Error(`В ответе backend отсутствует поле ${key}.`); return v[key] as string; };
  const num = (key: string) => { if (typeof v[key] !== 'number' || !Number.isFinite(v[key])) throw new Error(`Некорректное числовое поле ${key}.`); return v[key] as number; };
  const urgency = str('urgency');
  if (!['critical','soon','planned'].includes(urgency)) throw new Error('Некорректный уровень срочности.');
  const textFields=['id','sku','bomId','product','category','supplier','warehouse','unit','justification'].map(str);
  // Reject obvious PII indicators in all displayed/export-adjacent text; never echo a bad value.
  const piiPattern=/(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?\d[\d ()-]{7,}\d)|\b(?:customer|client|клиент|заказчик|телефон|почта|e-mail|email)\b)/i;
  if (textFields.some(text=>piiPattern.test(text))) throw new Error('Backend вернул поле с возможными персональными данными. Строка скрыта; проверьте API контракт.');
  const [id,sku,bomId,product,category,supplier,warehouse,unit,justification]=textFields;
  return { id,sku,bomId,product,category,supplier,warehouse,recommendedQty:num('recommendedQty'),quantity:num('recommendedQty'),unit,urgency:urgency as Urgency,stock:num('stock'),monthlyUse:num('monthlyUse'),leadDays:num('leadDays'),justification,status:'pending',reviewed:false };
}

export async function getOrders(): Promise<OrderLine[]> {
  if (isMock) return mockLines.map(x => ({...x}));
  const payload = await request<{lines:unknown[]}>('/api/orders');
  if (!Array.isArray(payload.lines)) throw new Error('Ожидался массив lines в /api/orders.');
  return payload.lines.map(safeLine);
}
export async function calculate(scope: CalculationRequest): Promise<OrderLine[]> {
  if (isMock) { await new Promise(r=>setTimeout(r,500)); return mockLines.filter(x=>(!scope.warehouse||x.warehouse===scope.warehouse)&&(!scope.category||x.category===scope.category)).map(x=>({...x})); }
  const response = await request<CalculationResponse>('/api/calculate',{method:'POST',body:JSON.stringify(scope)});
  if (!response || !Array.isArray(response.lines)) throw new Error('Ожидался массив lines в ответе /api/calculate.');
  return response.lines.map(safeLine);
}
