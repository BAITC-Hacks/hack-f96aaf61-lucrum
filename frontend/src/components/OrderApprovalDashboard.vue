<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

type OrderItem = {
  id: string;
  sku: string;
  product: string;
  supplier: string;
  quantity: number;
  status: 'pending' | 'approved';
};

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
const items = ref<OrderItem[]>([]);
const selectedIds = ref<Set<string>>(new Set());
const loading = ref(false);
const confirming = ref(false);
const exporting = ref(false);
const errorMessage = ref('');
const successMessage = ref('');
const exportDate = ref('');
const exportSupplier = ref('');

const pendingItems = computed(() => items.value.filter(item => item.status === 'pending'));
const supplierOptions = computed(() => [...new Set(pendingItems.value.map(item => item.supplier))].sort());
const allSelected = computed(() => pendingItems.value.length > 0 && pendingItems.value.every(item => selectedIds.value.has(item.id)));

const piiTextPattern = /(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:customer|client|клиент|заказчик|телефон|почта|e-mail|email|фио|контактные данные)\b)/i;
const phonePattern = /(?:\+?\d[\d ()-]{7,}\d)/;

function hasObviousPii(value: string): boolean {
  return piiTextPattern.test(value);
}

function safeOrder(value: unknown): OrderItem {
  if (!value || typeof value !== 'object') throw new Error('The orders response contains an invalid item.');
  const row = value as Record<string, unknown>;
  const idValue = row.id;
  const id = typeof idValue === 'string' || typeof idValue === 'number' ? String(idValue) : '';
  const sku = typeof row.sku === 'string' ? row.sku : '';
  const productValue = row.product;
  const product = typeof productValue === 'string' ? productValue : '';
  const supplier = typeof row.supplier === 'string' ? row.supplier : '';
  const quantityValue = row.quantity ?? row.recommendedQty;
  const quantity = typeof quantityValue === 'number' ? quantityValue : Number.NaN;
  const status = row.status === 'approved' ? 'approved' : 'pending';

  if (!id || !sku || !product || !supplier || !Number.isFinite(quantity) || quantity < 0) {
    throw new Error('The orders response is missing required fields.');
  }
  const displayText = [id, sku, product, supplier];
  if (displayText.some(hasObviousPii) || [id, sku, product, supplier].some(value => phonePattern.test(value))) {
    throw new Error('Possible personal data was returned by the API. The order list was hidden.');
  }
  return { id, sku, product, supplier, quantity, status };
}

async function fetchJson(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers }
  });
  if (!response.ok) throw new Error(`Request failed (HTTP ${response.status}).`);
  if (response.status === 204) return undefined;
  try {
    return await response.json();
  } catch {
    throw new Error('The orders endpoint returned invalid JSON.');
  }
}

async function loadOrders(): Promise<void> {
  loading.value = true;
  errorMessage.value = '';
  try {
    const payload = await fetchJson('/api/orders');
    let rawItems: unknown;
    if (Array.isArray(payload)) rawItems = payload;
    else if (payload && typeof payload === 'object') {
      const response = payload as Record<string, unknown>;
      rawItems = Array.isArray(response.orders) ? response.orders : response.lines;
    }
    if (!Array.isArray(rawItems)) throw new Error('The orders response did not contain an orders list.');
    const safeItems = rawItems.map(safeOrder);
    items.value = safeItems;
    selectedIds.value = new Set();
  } catch (error) {
    // Keep API response bodies and suspect values out of the UI and logs.
    errorMessage.value = error instanceof Error ? error.message : 'Could not load orders.';
  } finally {
    loading.value = false;
  }
}

function toggleItem(id: string, checked: boolean): void {
  const next = new Set(selectedIds.value);
  checked ? next.add(id) : next.delete(id);
  selectedIds.value = next;
  successMessage.value = '';
}

function toggleAll(checked: boolean): void {
  selectedIds.value = checked ? new Set(pendingItems.value.map(item => item.id)) : new Set();
  successMessage.value = '';
}

function handleSelectAll(event: Event): void {
  if (event.target instanceof HTMLInputElement) toggleAll(event.target.checked);
}

function handleSelectItem(id: string, event: Event): void {
  if (event.target instanceof HTMLInputElement) toggleItem(id, event.target.checked);
}

async function confirmSelected(): Promise<void> {
  const ids = [...selectedIds.value].filter(id => pendingItems.value.some(item => item.id === id));
  if (!ids.length) return;

  confirming.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  const approvedIds: string[] = [];
  const failedIds: string[] = [];

  // Each approval is a manager-triggered request. It confirms an item only; it never dispatches it.
  for (const id of ids) {
    try {
      const query = new URLSearchParams({ orderId: id });
      const response = await fetch(`${apiBase}/api/orders/approve?${query}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed: true })
      });
      if (!response.ok) throw new Error('approval request failed');
      approvedIds.push(id);
    } catch {
      failedIds.push(id);
    }
  }

  if (approvedIds.length) {
    const approved = new Set(approvedIds);
    items.value = items.value.map(item => approved.has(item.id) ? { ...item, status: 'approved' } : item);
    successMessage.value = `${approvedIds.length} item${approvedIds.length === 1 ? '' : 's'} confirmed.`;
  }
  selectedIds.value = new Set(failedIds);
  if (failedIds.length) {
    errorMessage.value = `${failedIds.length} approval request${failedIds.length === 1 ? '' : 's'} failed. Failed items remain selected so you can retry.`;
  }
  confirming.value = false;
}

function parseCsv(text: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  const source = text.replace(/^\uFEFF/, '');

  for (let index = 0; index < source.length; index++) {
    const char = source[index];
    if (quoted) {
      if (char === '"' && source[index + 1] === '"') { cell += '"'; index++; }
      else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"' && cell.length === 0) quoted = true;
    else if (char === delimiter) { row.push(cell); cell = ''; }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && source[index + 1] === '\n') index++;
      row.push(cell);
      if (row.some(value => value.length)) rows.push(row);
      row = [];
      cell = '';
    } else cell += char;
  }
  if (quoted) throw new Error('The export CSV has an unterminated quoted field.');
  if (row.length || cell.length) {
    row.push(cell);
    if (row.some(value => value.length)) rows.push(row);
  }
  return rows;
}

function validateCsv(text: string): Blob {
  const firstLine = text.replace(/^\uFEFF/, '').split(/\r?\n/, 1)[0] ?? '';
  const delimiter = firstLine.includes(';') ? ';' : ',';
  const rows = parseCsv(text, delimiter);
  const expected = ['SKU', 'BOM_ID', 'WAREHOUSE', 'SUPPLIER', 'QUANTITY', 'UNIT'];
  if (!rows.length || rows[0].length !== expected.length || rows[0].some((cell, index) => cell.trim().toUpperCase() !== expected[index])) {
    throw new Error('The export format did not match the approved 1C columns. No file was downloaded.');
  }
  for (const row of rows.slice(1)) {
    if (row.length !== expected.length) throw new Error('The export contains an invalid row. No file was downloaded.');
    if (row.some(hasObviousPii) || [row[2], row[3]].some(value => phonePattern.test(value))) {
      throw new Error('Possible personal data was detected in the export. No file was downloaded.');
    }
  }
  const csv = rows.map(row => row.map(value => `"${value.replace(/"/g, '""')}"`).join(';')).join('\r\n');
  return new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8' });
}

async function downloadCsv(): Promise<void> {
  exporting.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    const query = new URLSearchParams();
    if (exportDate.value) query.set('date', exportDate.value);
    if (exportSupplier.value) query.set('supplier', exportSupplier.value);
    const queryString = query.toString();
    const suffix = queryString ? `?${queryString}` : '';
    const response = await fetch(`${apiBase}/api/orders/export-1c${suffix}`, { headers: { Accept: 'text/csv' } });
    const body = await response.text();

    if (/no approved positions found/i.test(body)) {
      successMessage.value = 'No approved positions found for the selected filters.';
      return;
    }
    if (!response.ok) throw new Error(`Export failed (HTTP ${response.status}).`);
    const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
    if (!/(?:text\/csv|application\/csv|application\/vnd\.ms-excel)/.test(contentType)) {
      throw new Error('The server did not return a CSV file.');
    }

    const blob = validateCsv(body);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'approved-orders-1c.csv';
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    successMessage.value = 'The approved 1C CSV download has started.';
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Could not export the CSV.';
  } finally {
    exporting.value = false;
  }
}

onMounted(loadOrders);
</script>

<template>
  <section class="orders-card" aria-labelledby="orders-title">
    <header class="orders-header">
      <div>
        <p class="eyebrow">PROCUREMENT</p>
        <h1 id="orders-title">Pending orders</h1>
        <p class="muted">Select the items to review, then confirm them explicitly.</p>
      </div>
      <button class="button button-secondary" type="button" :disabled="loading" @click="loadOrders">
        {{ loading ? 'Loading…' : 'Refresh' }}
      </button>
    </header>

    <div v-if="errorMessage" class="notice notice-error" role="alert">{{ errorMessage }}</div>
    <div v-if="successMessage" class="notice notice-success" role="status">{{ successMessage }}</div>

    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th scope="col">
              <input
                aria-label="Select all pending orders"
                type="checkbox"
                :checked="allSelected"
                :disabled="loading || !pendingItems.length"
                @change="handleSelectAll"
              />
            </th>
            <th scope="col">SKU</th>
            <th scope="col">Item</th>
            <th scope="col">Supplier</th>
            <th scope="col" class="number">Quantity</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="5" class="empty">Loading pending orders…</td></tr>
          <tr v-else-if="!pendingItems.length"><td colspan="5" class="empty">No pending orders.</td></tr>
          <tr v-for="item in pendingItems" :key="item.id">
            <td>
              <input
                :aria-label="`Select ${item.sku}`"
                type="checkbox"
                :checked="selectedIds.has(item.id)"
                @change="handleSelectItem(item.id, $event)"
              />
            </td>
            <td class="code">{{ item.sku }}</td>
            <td>{{ item.product }}</td>
            <td>{{ item.supplier }}</td>
            <td class="number">{{ item.quantity }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="orders-footer">
      <span class="muted">{{ selectedIds.size }} selected</span>
      <button class="button button-primary" type="button" :disabled="!selectedIds.size || confirming" @click="confirmSelected">
        {{ confirming ? 'Confirming…' : 'Confirm Selected' }}
      </button>
    </footer>

    <section class="export-panel" aria-labelledby="export-title">
      <div>
        <h2 id="export-title">1C export</h2>
        <p class="muted">Download manager-approved positions in the 1C CSV format.</p>
      </div>
      <div class="export-controls">
        <label>
          <span>Date (optional)</span>
          <input v-model="exportDate" type="date" />
        </label>
        <label>
          <span>Supplier (optional)</span>
          <input v-model.trim="exportSupplier" list="order-suppliers" type="text" maxlength="120" placeholder="All suppliers" />
          <datalist id="order-suppliers">
            <option v-for="supplier in supplierOptions" :key="supplier" :value="supplier" />
          </datalist>
        </label>
        <button class="button button-primary" type="button" :disabled="exporting" @click="downloadCsv">
          {{ exporting ? 'Preparing CSV…' : 'Download 1C CSV' }}
        </button>
      </div>
    </section>

    <p class="dispatch-note">Confirmation records manager approval only. Orders are never sent to suppliers automatically.</p>
  </section>
</template>

<style scoped>
.orders-card{max-width:1100px;margin:2rem auto;padding:clamp(1rem,3vw,2rem);background:#fff;border:1px solid #e5e9e3;border-radius:14px;color:#233128;box-shadow:0 12px 36px rgb(23 37 31 / 6%);font:14px/1.5 system-ui,sans-serif}
.orders-header,.orders-footer,.export-panel,.export-controls{display:flex;align-items:center;justify-content:space-between;gap:1rem}
.orders-header{margin-bottom:1.25rem}.eyebrow{margin:0 0 .25rem;color:#6b805e;font-size:.7rem;font-weight:800;letter-spacing:.12em}.orders-header h1,.export-panel h2{margin:0;color:#1d3427;font-size:1.35rem;font-weight:750}.muted{margin:.25rem 0 0;color:#718071;font-size:.85rem}
.table-scroll{overflow-x:auto;border:1px solid #e8ece6;border-radius:9px}table{width:100%;border-collapse:collapse;min-width:620px}th,td{padding:.8rem .9rem;border-bottom:1px solid #edf0eb;text-align:left}th{background:#f7f9f5;color:#637260;font-size:.72rem;letter-spacing:.04em;text-transform:uppercase}tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:#fbfcfa}.number{text-align:right}.code{color:#526849;font-family:ui-monospace,monospace;font-size:.82rem}.empty{text-align:center;color:#718071;padding:2rem}
input[type=checkbox]{width:1rem;height:1rem;accent-color:#53763d;cursor:pointer}.orders-footer{padding:1rem 0 1.25rem}.button{min-height:2.5rem;padding:.6rem 1rem;border:1px solid transparent;border-radius:7px;font:650 .85rem system-ui,sans-serif;cursor:pointer;transition:background .15s,border-color .15s}.button:focus-visible,input:focus-visible{outline:3px solid #a9cf78;outline-offset:2px}.button:disabled{opacity:.55;cursor:not-allowed}.button-primary{background:#53763d;color:#fff}.button-primary:hover:not(:disabled){background:#42622e}.button-secondary{border-color:#dce3da;background:#fff;color:#344537}.button-secondary:hover:not(:disabled){background:#f2f6ef}
.notice{margin:.8rem 0;padding:.7rem .85rem;border-radius:7px;font-size:.88rem}.notice-error{border:1px solid #f1cdc7;background:#fff0ee;color:#963f33}.notice-success{border:1px solid #d6e5ca;background:#eff6e8;color:#4f6d37}
.export-panel{align-items:flex-start;margin-top:1rem;padding:1rem;border:1px solid #e5e9e3;border-radius:9px;background:#fafbf9}.export-controls{flex-wrap:wrap;justify-content:flex-end}.export-controls label{display:flex;flex-direction:column;gap:.3rem;color:#667462;font-size:.72rem;font-weight:650}.export-controls input{min-height:2.5rem;min-width:10rem;padding:.5rem .65rem;border:1px solid #dce3da;border-radius:6px;background:#fff;color:#25342a;font:400 .85rem system-ui,sans-serif}.export-controls input[type=date]{min-width:9rem}.dispatch-note{margin:1rem 0 0;color:#6d805e;font-size:.76rem}
@media(max-width:700px){.orders-card{margin:1rem .5rem}.orders-header{align-items:flex-start}.orders-header h1{font-size:1.2rem}.export-panel,.export-controls{align-items:stretch;flex-direction:column}.export-controls label,.export-controls input,.export-controls .button{width:100%}.orders-footer{align-items:flex-start}.button{white-space:nowrap}}
</style>
