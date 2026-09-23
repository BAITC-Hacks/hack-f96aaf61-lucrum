import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Activity, Bell, Boxes, Check, ChevronDown, CircleAlert, ClipboardCheck,
  Download, FileSpreadsheet, LayoutDashboard, Layers3, PackageCheck,
  RefreshCw, Search, Settings, ShieldCheck, SlidersHorizontal,
  Warehouse as WarehouseIcon,
} from 'lucide-react';
import { Badge } from '../components/ui/Badge';
import { BarList } from '../components/ui/BarList';
import { Card } from '../components/ui/Card';
import { approveOrders, calculate, checkHealth, exportOrders, getOrders, getStock, isMock, mergeStock, uploadReport } from '../data/api';
import type { OrderLine, Urgency } from '../data/types';

const money = new Intl.NumberFormat('ru-RU');
const urgencyName: Record<Urgency, string> = { critical: 'Высокая', soon: 'Средняя', planned: 'Плановая' };

export default function App() {
  const [lines, setLines] = useState<OrderLine[]>([]);
  const [warehouse, setWarehouse] = useState('Все склады');
  const [category, setCategory] = useState('Все категории');
  const [supplier, setSupplier] = useState('Все поставщики');
  const [urgency, setUrgency] = useState('Любая срочность');
  const [approvalStatus, setApprovalStatus] = useState('Любой статус');
  const [busy, setBusy] = useState(false);
  const [calculating, setCalculating] = useState(false);
  const [loadingOrders, setLoadingOrders] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [isStale, setIsStale] = useState(false);
  const [selectedItemIds, setSelectedItemIds] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [stockError, setStockError] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const [serviceStatus, setServiceStatus] = useState<'demo' | 'checking' | 'online' | 'offline'>(isMock ? 'demo' : 'checking');
  const [approvedBy, setApprovedBy] = useState('manager');
  const [managerNote, setManagerNote] = useState('');
  const [exportBusy, setExportBusy] = useState(false);
  const [now, setNow] = useState(new Date());
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadMessage, setUploadMessage] = useState('');
  const [dragging, setDragging] = useState(false);

  const warehouses = useMemo(() => ['Все склады', ...new Set(lines.map((line) => line.warehouse))], [lines]);
  const categories = useMemo(() => ['Все категории', ...new Set(lines.map((line) => line.category))], [lines]);
  const suppliers = useMemo(() => ['Все поставщики', ...new Set(lines.map((line) => line.supplierCode).filter(Boolean))], [lines]);

  useEffect(() => {
    let active = true;
    checkHealth()
      .then(() => { if (active) setServiceStatus(isMock ? 'demo' : 'online'); })
      .catch(() => { if (active) setServiceStatus('offline'); });
    getOrders()
      .then(async (data) => {
        if (!active) return;
        setRunId(data.runId);
        setNow(data.createdAt ? new Date(data.createdAt) : new Date());
        setLines(data.lines);
        try {
          const stock = await getStock();
          if (active) setLines(mergeStock(data.lines, stock));
        } catch (cause: unknown) {
          if (active) setStockError(cause instanceof Error ? cause.message : 'Не удалось загрузить складские остатки.');
        }
      })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : 'Не удалось загрузить заказы.'); })
      .finally(() => { if (active) setLoadingOrders(false); });
    return () => { active = false; };
  }, []);

  const filtered = lines.filter((line) =>
    (warehouse === 'Все склады' || line.warehouse === warehouse)
    && (category === 'Все категории' || line.category === category)
    && (supplier === 'Все поставщики' || line.supplierCode === supplier)
    && (urgency === 'Любая срочность' || line.urgency === urgency)
    && (approvalStatus === 'Любой статус'
      || (approvalStatus === 'Ожидают проверки' && !line.reviewed && line.status !== 'approved')
      || (approvalStatus === 'Проверены' && line.reviewed && line.status !== 'approved')
      || (approvalStatus === 'Подтверждены' && line.status === 'approved')),
  );
  const urgent = filtered.filter((line) => line.urgency === 'critical').length;
  const quantity = filtered.reduce((sum, line) => sum + line.quantity, 0);
  const reviewed = filtered.filter((line) => line.reviewed || line.status === 'approved').length;
  const allApproved = filtered.length > 0 && filtered.every((line) => line.status === 'approved');
  const hasApproved = lines.some((line) => line.status === 'approved');
  const pendingVisible = filtered.filter((line) => line.status !== 'approved');
  const selectedVisibleIds = pendingVisible.filter((line) => selectedItemIds.includes(line.id)).map((line) => line.id);
  const allVisibleSelected = pendingVisible.length > 0 && selectedVisibleIds.length === pendingVisible.length;
  const selectedPending = lines.filter((line) => selectedItemIds.includes(line.id) && line.status !== 'approved');
  const categorySummary = Array.from(new Set(filtered.map((line) => line.category))).map((name) => ({
    name,
    count: filtered.filter((line) => line.category === name).length,
    units: filtered.filter((line) => line.category === name).reduce((sum, line) => sum + line.quantity, 0),
  }));
  const supplierSummary = Array.from(new Set(filtered.map((line) => line.supplier))).map((name) => ({
    name,
    count: filtered.filter((line) => line.supplier === name).length,
    units: filtered.filter((line) => line.supplier === name).reduce((sum, line) => sum + line.quantity, 0),
  }));
  const groupedRows = Array.from(new Set(filtered.map((line) => line.supplierCode || line.supplier))).map((key) => {
    const groupLines = filtered.filter((line) => (line.supplierCode || line.supplier) === key);
    return { key, code: groupLines[0]?.supplierCode ?? '', name: groupLines[0]?.supplier ?? key, lines: groupLines };
  });
  const approvalsLocked = isStale || busy || calculating || uploadBusy || refreshing;
  const editedRecommendations = filtered.some((line) => line.quantity !== line.recommendedQty);

  function toggleSupplierSelection(ids: string[], checked: boolean) {
    setSelectedItemIds((current) => checked
      ? Array.from(new Set([...current, ...ids]))
      : current.filter((id) => !ids.includes(id)));
    if (checked) setLines((current) => current.map((line) => ids.includes(line.id) ? { ...line, reviewed: true } : line));
  }

  function toggleItemSelection(id: string, checked: boolean) {
    setSelectedItemIds((current) => checked
      ? Array.from(new Set([...current, id]))
      : current.filter((selectedId) => selectedId !== id));
    if (checked) setLines((current) => current.map((line) => line.id === id ? { ...line, reviewed: true } : line));
  }

  function toggleVisibleSelection(checked: boolean) {
    const ids = pendingVisible.map((line) => line.id);
    setSelectedItemIds((current) => checked
      ? Array.from(new Set([...current, ...ids]))
      : current.filter((id) => !ids.includes(id)));
    if (checked) setLines((current) => current.map((line) => ids.includes(line.id) ? { ...line, reviewed: true } : line));
  }

  async function refreshLatest() {
    setRefreshing(true);
    setError('');
    try {
      const latest = await getOrders();
      setLines(latest.lines);
      setRunId(latest.runId);
      setNow(latest.createdAt ? new Date(latest.createdAt) : new Date());
      setSelectedItemIds([]);
      setWarehouse('Все склады');
      setCategory('Все категории');
      setSupplier('Все поставщики');
      setUrgency('Любая срочность');
      setApprovalStatus('Любой статус');
      setIsStale(false);
      setStockError('');
      try {
        const stock = await getStock();
        setLines(mergeStock(latest.lines, stock));
      } catch (cause: unknown) {
        setStockError(cause instanceof Error ? cause.message : 'Не удалось загрузить складские остатки.');
      }
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Не удалось обновить последнюю версию рекомендаций.');
      setIsStale(true);
    } finally {
      setRefreshing(false);
    }
  }

  async function runCalculation() {
    setBusy(true);
    setCalculating(true);
    setIsStale(true);
    setSelectedItemIds([]);
    setError('');
    try {
      const next = await calculate({
        warehouse: warehouse === 'Все склады' ? undefined : warehouse,
        category: category === 'Все категории' ? undefined : category,
      });
      setRunId(next.runId);
      setNow(next.createdAt ? new Date(next.createdAt) : new Date());
      setLines(next.lines);
      setIsStale(false);
      setSupplier('Все поставщики');
      setUrgency('Любая срочность');
      setApprovalStatus('Любой статус');
      setStockError('');
      try {
        const stock = await getStock(warehouse === 'Все склады' ? undefined : warehouse);
        setLines(mergeStock(next.lines, stock));
      } catch (cause: unknown) {
        setStockError(cause instanceof Error ? cause.message : 'Не удалось загрузить складские остатки.');
      }
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Не удалось выполнить расчёт.');
    } finally {
      setBusy(false);
      setCalculating(false);
    }
  }

  function patchLine(id: string, updates: Partial<OrderLine>) {
    setLines((current) => current.map((line) => line.id === id && line.status !== 'approved'
      ? { ...line, ...updates, ...('quantity' in updates ? { reviewed: false } : {}), status: 'pending' }
      : line));
  }

  async function approveVisible() {
    if (approvalsLocked) return;
    const targetLines = lines.filter((line) => selectedItemIds.includes(line.id) && line.status !== 'approved');
    if (!targetLines.length || targetLines.some((line) => !line.reviewed)) {
      setError('Перед подтверждением проверьте каждую позицию.');
      return;
    }
    if (targetLines.some((line) => line.quantity !== line.recommendedQty)) {
      setError('Текущий API не принимает изменённое количество. Верните расчётное значение перед согласованием.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const latest = await getOrders().catch((cause: unknown) => {
        setIsStale(true);
        setSelectedItemIds([]);
        throw cause;
      });
      if (latest.runId !== runId) {
        setLines(latest.lines);
        setRunId(latest.runId);
        setNow(latest.createdAt ? new Date(latest.createdAt) : new Date());
        setSelectedItemIds([]);
        setIsStale(false);
        setError('В backend появился новый расчёт. Рекомендации обновлены, отметки проверки сброшены; проверьте позиции перед подтверждением.');
        return;
      }
      const result = await approveOrders(targetLines, { approvedBy, managerNote });
      const accepted = new Set([...result.approved, ...result.alreadyApproved]);
      setLines((current) => current.map((line) => accepted.has(line.id)
        ? { ...line, status: 'approved', reviewed: true, approvedBy: result.approvedBy ?? approvedBy, approvedAt: result.approvalTimestamp }
        : line));
      setSelectedItemIds([]);
    } catch (cause: unknown) {
      if (cause instanceof Error && 'status' in cause && cause.status === 409) {
        setIsStale(true);
        setSelectedItemIds([]);
        try {
          const latest = await getOrders();
          setRunId(latest.runId);
          setLines(latest.lines);
          setIsStale(false);
          setSupplier('Все поставщики');
          setUrgency('Любая срочность');
          setApprovalStatus('Любой статус');
          setError('Расчёт изменился: обновлены актуальные позиции и сброшены отметки проверки. Проверьте их перед повторным согласованием.');
        } catch (refreshError: unknown) {
          setError(refreshError instanceof Error ? refreshError.message : 'Позиции устарели; обновите список и попробуйте снова.');
        }
      } else {
        setError(cause instanceof Error ? cause.message : 'Не удалось подтвердить позиции.');
      }
    } finally {
      setBusy(false);
    }
  }

  async function exportCsv() {
    if (!hasApproved) {
      setError('Сначала подтвердите позиции кнопкой менеджера.');
      return;
    }
    setExportBusy(true);
    setError('');
    try {
      const { blob, filename } = await exportOrders({
        supplierCode: supplier === 'Все поставщики' ? undefined : supplier,
        warehouse: warehouse === 'Все склады' ? undefined : warehouse,
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause: unknown) {
      if (cause instanceof Error && 'status' in cause && cause.status === 404) {
        setError('В текущем расчёте нет подтверждённых позиций для экспорта. Подтвердите заказ или измените фильтры.');
      } else {
        setError(cause instanceof Error ? cause.message : 'Не удалось выгрузить файл для 1С.');
      }
    } finally {
      setExportBusy(false);
    }
  }

  async function handleUpload(file?: File) {
    if (!file) return;
    if (loadingOrders || busy || calculating || refreshing || uploadBusy) {
      setError('Дождитесь завершения текущей операции перед загрузкой файла.');
      return;
    }
    if (!/\.xlsx$/i.test(file.name)) { setError('Backend принимает только файлы .xlsx.'); return; }
    if (file.size > 25 * 1024 * 1024) { setError('Размер файла превышает лимит 25 MiB.'); return; }
    setUploadBusy(true);
    setIsStale(true);
    setSelectedItemIds([]);
    setUploadMessage('');
    setError('');
    try {
      await uploadReport(file);
      setLines([]);
      setRunId(null);
      setSelectedItemIds([]);
      setStockError('');
      setSupplier('Все поставщики');
      setUrgency('Любая срочность');
      setApprovalStatus('Любой статус');
      setUploadMessage('Файл загружен. Предыдущий расчёт сброшен; нажмите «Рассчитать», чтобы получить новые рекомендации.');
      const latest = await getOrders();
      if (latest.lines.length) throw new Error('После загрузки backend вернул старые рекомендации вместо пустого расчёта. Данные оставлены заблокированными; обновите их перед работой.');
      setRunId(latest.runId);
      setNow(latest.createdAt ? new Date(latest.createdAt) : new Date());
      setIsStale(false);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить отчёт.');
    } finally {
      setUploadBusy(false);
    }
  }

  return (
    <div className="luc-app">
      <header className="luc-topbar">
        <a className="luc-brand" href="#dashboard" aria-label="Lucrum dashboard">
          <span className="luc-brand-mark"><Layers3 size={18} /></span>
          <span>LUCRUM</span>
        </a>
        <nav className="luc-topnav" aria-label="Основная навигация">
          <a className="is-active" href="#dashboard"><LayoutDashboard size={14} /> Dashboard</a>
          <a href="#orders"><Boxes size={14} /> Orders</a>
          <a href="#inventory"><WarehouseIcon size={14} /> Inventory</a>
          <a href="#analytics"><Activity size={14} /> Analytics</a>
          <a href="#settings"><Settings size={14} /> Settings</a>
        </nav>
        <form className="luc-global-search" method="get">
          <label htmlFor="project-search">Search projects</label>
          <div><Search size={14} /><input id="project-search" name="q" type="search" placeholder="Search" /></div>
        </form>
        <button className="luc-icon-button" type="button" aria-label="Уведомления"><Bell size={16} /><i /></button>
        <button className="luc-profile" type="button">Менеджер <b>Елена Волкова</b><ChevronDown size={13} /></button>
      </header>

      <div className="luc-layout">
        <aside className="luc-sidebar">
          <section className="luc-company">
            <b>Elektrokomplekt LLP</b>
            <span>Supplier order recommendations</span>
            <span className={`luc-api-status ${serviceStatus}`}><i /> {serviceStatus === 'demo' ? 'Демо API' : serviceStatus === 'checking' ? 'Проверка API' : serviceStatus === 'online' ? 'API доступен' : 'API недоступен'}</span>
          </section>
          <div className="luc-filter-title"><SlidersHorizontal size={14} /> ФИЛЬТРЫ</div>
          <FilterSelect label="Склад" value={warehouse} options={warehouses} onChange={setWarehouse} />
          <FilterSelect label="Категория" value={category} options={categories} onChange={setCategory} />
          <FilterSelect label="Поставщик" value={supplier} options={suppliers} onChange={setSupplier} optionLabel={(code) => code === 'Все поставщики' ? code : `${lines.find((line) => line.supplierCode === code)?.supplier ?? code} (${code})`} />
          <FilterSelect label="Срочность" value={urgency} options={['Любая срочность', 'critical', 'soon', 'planned']} onChange={setUrgency} optionLabel={(value) => ({ critical: 'Высокая', soon: 'Средняя', planned: 'Плановая' }[value] ?? value)} />
          <FilterSelect label="Согласование" value={approvalStatus} options={['Любой статус', 'Ожидают проверки', 'Проверены', 'Подтверждены']} onChange={setApprovalStatus} />
          <section
            className={`luc-upload ${dragging ? 'is-dragging' : ''}`}
            onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => { event.preventDefault(); setDragging(false); void handleUpload(event.dataTransfer.files[0]); }}
          >
            <FileSpreadsheet size={17} />
            <b>Загрузить отчёт</b>
            <span>{uploadMessage || 'Перетащите Excel или выберите файл'}</span>
            {uploadBusy && <div className="luc-upload-progress" aria-label="Загрузка отчёта"><i /></div>}
            <label className={`luc-upload-button ${uploadBusy || busy || loadingOrders || refreshing ? 'is-disabled' : ''}`}>{uploadBusy ? <><RefreshCw size={12} className="luc-spin" /> Загружаем…</> : 'Выбрать файл'}<input type="file" accept=".xlsx" disabled={uploadBusy || busy || loadingOrders || refreshing} hidden onChange={(event) => { void handleUpload(event.target.files?.[0]); event.currentTarget.value = ''; }} /></label>
          </section>
        </aside>

        <main className="luc-main" id="dashboard">
          <div className="luc-heading-row">
            <div>
              <div className="luc-eyebrow">LUCRUM <span>·</span> УПРАВЛЕНИЕ ПОПОЛНЕНИЕМ</div>
              <h1>Обзор пополнения</h1>
              <p>Рекомендации backend по заказам поставщикам. Подтверждайте позиции вручную.</p>
            </div>
            <button className="luc-calculate" onClick={runCalculation} disabled={busy || uploadBusy || refreshing || loadingOrders}>
              <RefreshCw size={15} className={calculating ? 'luc-spin' : ''} /> {calculating ? 'Считаем…' : 'Рассчитать'}
            </button>
          </div>

          {isMock && <div className="luc-demo-banner"><CircleAlert size={15} /> Демо-режим: отображаются синтетические данные. Подключите API через <code>VITE_API_BASE_URL</code>.</div>}
          {!isMock && <div className="luc-contract-note">Коды IEK и SYSTEMELECTRIC могут быть предварительными группировочными кодами, а срок поставки в наборах без явного значения — значением по умолчанию 30 дней.</div>}
          {isStale && <div className="luc-stale-warning" role="alert"><CircleAlert size={18} /><div><b>Данные расчёта могут быть устаревшими</b><span>{calculating ? 'Выполняется новый расчёт; старые ID уже нельзя согласовывать.' : uploadBusy ? 'Файл загружается; прежние ID будут аннулированы.' : 'Согласование и экспорт заблокированы, пока вы не обновите список последнего расчёта.'}</span></div><button onClick={refreshLatest} disabled={busy || uploadBusy || refreshing || calculating}><RefreshCw size={13} className={refreshing ? 'luc-spin' : ''} /> {refreshing ? 'Обновляем…' : 'Обновить рекомендации'}</button></div>}
          {error && <div className="luc-error" role="alert"><CircleAlert size={16} /> {error}<button onClick={() => setError('')} aria-label="Закрыть">×</button></div>}
          {stockError && <div className="luc-contract-note" role="status"><CircleAlert size={14} /> Остатки не загружены: {stockError}</div>}

          <section className="luc-metrics" aria-label="Сводка заказов">
            <Metric label="Ожидают проверки" value={String(filtered.length - reviewed)} sub="Активные рекомендации" icon={<ClipboardCheck />} tone="blue" />
            <Metric label="Требуют согласования" value={String(reviewed)} sub={`${reviewed} из ${filtered.length} проверено`} icon={<ShieldCheck />} tone="amber" />
            <Metric label="Статус экспорта 1С" value={hasApproved ? 'Готов' : 'Ожидает'} sub={hasApproved ? 'Есть согласованные позиции' : 'После подтверждения менеджером'} icon={<FileSpreadsheet />} tone={hasApproved ? 'green' : 'blue'} />
            <Metric label="Высокая срочность" value={String(urgent)} sub={`${money.format(quantity)} ед. к заказу`} icon={<CircleAlert />} tone="red" />
          </section>

          <div className="luc-section-heading" id="orders">
            <div><h2>Активные предложения заказа</h2><p>{filtered.length} позиций · обновлено {new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(now)}{runId ? ` · Расчёт ${runId.slice(0, 8)}` : ' · расчёт ещё не выполнялся'}</p></div>
            <button className="luc-export" onClick={exportCsv} disabled={!hasApproved || exportBusy || approvalsLocked}><Download size={14} /> {exportBusy ? 'Готовим CSV…' : 'Экспорт в 1С'}</button>
          </div>

          <div className="luc-workspace">
            <section className="luc-table-card" aria-label="Рекомендации к заказу">
              <div className="luc-table-topline"><span><PackageCheck size={15} /> {supplier === 'Все поставщики' ? 'Все поставщики' : `${lines.find((line) => line.supplierCode === supplier)?.supplier ?? supplier} · ${supplier}`}</span><span>Выбрано: {selectedItemIds.length} · {reviewed}/{filtered.length} проверено</span></div>
              <div className="luc-table-scroll" aria-busy={loadingOrders || calculating}>
                <table className="luc-table">
                  <thead><tr><th><input type="checkbox" className="luc-row-checkbox" aria-label="Выбрать все видимые позиции" checked={allVisibleSelected} disabled={approvalsLocked || pendingVisible.length === 0} onChange={(event) => toggleVisibleSelection(event.target.checked)} /></th><th>SKU / артикул</th><th>Наименование</th><th>Остаток</th><th>В пути</th><th>Спрос / 30 дней</th><th>Поставщик</th><th>К заказу</th><th>Срочность</th><th>Действия</th></tr></thead>
                  <tbody>
                    {(loadingOrders || (calculating && !lines.length)) && <tr className="luc-skeleton-row"><td colSpan={10}><span className="luc-skeleton" /><span className="luc-skeleton" /><span className="luc-skeleton" /></td></tr>}
                    {groupedRows.flatMap((group) => {
                      const pendingCount = group.lines.filter((line) => line.status !== 'approved').length;
                      const pendingIds = group.lines.filter((line) => line.status !== 'approved').map((line) => line.id);
                      const groupSelected = pendingIds.length > 0 && pendingIds.every((id) => selectedItemIds.includes(id));
                      const groupSelectable = !approvalsLocked && pendingCount > 0;
                      return [
                      <tr key={`${group.key}-supplier`} className={`luc-supplier-group ${groupSelected ? 'is-selected' : ''}`}>
                        <td colSpan={10}>
                          <label className="luc-supplier-select">
                            <input type="checkbox" checked={groupSelected} disabled={!groupSelectable} aria-label={`Выбрать все позиции поставщика ${group.name}`} onChange={(event) => toggleSupplierSelection(pendingIds, event.target.checked)} />
                            <span>Выбрать все позиции</span>
                          </label>
                          <b>{group.name}</b><code>{group.code || 'код не задан'}</code>
                          <span className="luc-group-count">{group.lines.length} позиций · {pendingCount} ожидают согласования · {money.format(group.lines.reduce((sum, line) => sum + line.quantity, 0))} ед.</span>
                        </td>
                      </tr>,
                      ...group.lines.map((line) => (
                      <tr key={line.id} className={`${line.status === 'approved' ? 'is-approved' : ''} ${isStale ? 'is-stale' : ''}`}>
                        <td><input type="checkbox" className="luc-row-checkbox" aria-label={`Выбрать ${line.sku} ${line.product}`} checked={line.status === 'approved' || selectedItemIds.includes(line.id)} disabled={line.status === 'approved' || approvalsLocked} onChange={(event) => toggleItemSelection(line.id, event.target.checked)} /></td>
                        <td><span className="luc-sku">{line.sku}</span><small>{line.bomId ? `BOM ${line.bomId}` : line.category}</small></td>
                        <td><b className="luc-product">{line.product}</b><small>{line.category}</small><span className="luc-justification" title={`${line.justification}${line.seasonality ? ` · Сезонность: ${line.seasonality}` : ''}${line.moq ? ` · MOQ: ${line.moq}` : ''}`}>{line.justification}{line.seasonality ? ` · ${line.seasonality}` : ''}{line.moq ? ` · MOQ ${line.moq}` : ''}</span></td>
                        <td><b>{line.stock === undefined ? '—' : money.format(line.stock)}</b><small>{line.stockout ? 'Дефицит' : line.stock === undefined ? 'нет данных' : line.unit}</small></td>
                        <td><span title="Поле по остаткам в пути отсутствует в текущем API-контракте">—</span><small>нет данных</small></td>
                        <td><b>{money.format(line.monthlyUse)}</b><small>{line.unit}</small></td>
                        <td><span className="luc-supplier">{line.supplier}</span><small>{line.supplierCode || 'код не задан'} · {line.warehouse}</small></td>
                        <td><div className="luc-qty"><input id={`qty-${line.id}`} aria-label={`Количество для ${line.product}`} type="number" min="0" disabled={line.status === 'approved' || approvalsLocked} value={line.quantity} onChange={(event) => patchLine(line.id, { quantity: Math.max(0, Number(event.target.value)) })} /><span>{line.unit}</span></div></td>
                        <td><Badge className={`luc-priority ${line.urgency}`} variant={line.urgency === 'critical' ? 'error' : line.urgency === 'soon' ? 'warning' : 'success'}>{urgencyName[line.urgency]}</Badge></td>
                        <td>{line.status === 'approved' ? <Badge className="luc-approved-badge" variant="success"><Check size={12} /> Согласовано</Badge> : <div className="luc-row-actions"><button className={`luc-row-review ${line.reviewed ? 'is-reviewed' : ''}`} disabled={approvalsLocked} onClick={() => patchLine(line.id, { reviewed: !line.reviewed })}>{line.reviewed ? <><Check size={13} /> Проверено</> : 'Проверить'}</button><button className="luc-adjust" disabled={approvalsLocked} onClick={() => document.getElementById(`qty-${line.id}`)?.focus()}>Изменить</button></div>}</td>
                      </tr>
                      )),
                    ];
                    })}
                  </tbody>
                </table>
                {!loadingOrders && !calculating && !filtered.length && <div className="luc-empty">По выбранным фильтрам позиций нет.</div>}
              </div>
              <div className="luc-table-footer"><span>Показано {filtered.length} рекомендаций</span><span><Activity size={13} /> Источник: {isMock ? 'синтетический набор' : 'backend API'}</span></div>
            </section>

            <aside className="luc-approval-panel">
              <div className={`luc-approval-status ${hasApproved ? 'is-done' : ''} ${isStale ? 'is-stale' : ''}`}><ShieldCheck size={19} /><span>{isStale ? 'Обновите данные' : allApproved ? 'Все позиции согласованы' : hasApproved ? 'Часть позиций согласована' : 'Требуется согласование'}</span></div>
              <h3>Подтверждение заказа</h3>
              <p>{isStale ? 'ID этого расчёта могут быть недействительны. Обновите рекомендации перед согласованием.' : hasApproved ? 'Согласованные позиции отмечены в таблице. Экспорт доступен для передачи в 1С.' : 'Выберите позиции чекбоксами, проверьте количество и подтвердите выбор вручную.'}</p>
              <label htmlFor="confirmed-count">Выбрано позиций</label>
              <div className="luc-confirmed-count"><input id="confirmed-count" value={selectedPending.length} readOnly /><span>из {lines.filter((line) => line.status !== 'approved').length}</span></div>
              <label className="luc-manager-label" htmlFor="approved-by">Ответственный менеджер</label>
              <input className="luc-manager-input" id="approved-by" value={approvedBy} onChange={(event) => setApprovedBy(event.target.value)} maxLength={120} />
              <label className="luc-manager-label" htmlFor="manager-note">Заметка к согласованию <span>(необязательно)</span></label>
              <textarea className="luc-manager-note" id="manager-note" value={managerNote} onChange={(event) => setManagerNote(event.target.value)} maxLength={1000} rows={3} placeholder="Комментарий для журнала согласования" />
              <small className="luc-note-count">{managerNote.length}/1000</small>
              {filtered.some((line) => line.quantity !== line.recommendedQty) && <div className="luc-contract-warning"><CircleAlert size={14} /><span>Текущий API подтверждает ID позиций, но не принимает изменённое количество. Верните расчётное количество для согласования.</span><button type="button" onClick={() => setLines((current) => current.map((line) => line.status === 'approved' || line.quantity === line.recommendedQty ? line : { ...line, quantity: line.recommendedQty, reviewed: false }))}>Вернуть расчётное</button></div>}
              <div className="luc-approval-checklist"><span><Check size={13} /> Количество и срочность проверены</span><span><Check size={13} /> Автоматическая отправка отключена</span></div>
              <button className="luc-submit" onClick={approveVisible} disabled={approvalsLocked || selectedPending.length === 0 || selectedPending.some((line) => !line.reviewed || line.quantity !== line.recommendedQty)}><ShieldCheck size={14} className={busy ? 'luc-spin' : ''} /> {busy ? 'Подтверждаем…' : `Согласовать выбранные (${selectedPending.length})`}</button>
              {hasApproved && <button className="luc-submit is-export" onClick={exportCsv} disabled={exportBusy || approvalsLocked}><Download size={14} /> {exportBusy ? 'Готовим файл…' : 'Скачать CSV для 1С'}</button>}
              <small className="luc-approval-note">Согласование фиксируется только после нажатия менеджером этой кнопки.</small>
            </aside>
          </div>

          <div className="luc-analytics" id="analytics">
            <Card className="luc-analytics-card"><div className="luc-card-heading"><div><h3>Объём по категориям</h3><p>Распределение рекомендованных единиц</p></div><Layers3 size={16} /></div><BarList data={categorySummary.map((item) => ({ name: `${item.name} · ${item.count} поз.`, value: item.units }))} valueFormatter={(value) => `${money.format(value)} ед.`} sortOrder="descending" /></Card>
            <Card className="luc-analytics-card"><div className="luc-card-heading"><div><h3>Поставщики</h3><p>Рекомендации по текущей выборке</p></div><Boxes size={16} /></div><BarList data={supplierSummary.map((item) => ({ name: `${item.name} · ${item.count} поз.`, value: item.units }))} valueFormatter={(value) => `${money.format(value)} ед.`} sortOrder="descending" /></Card>
          </div>
          <footer className="luc-footer"><span>© {new Date().getFullYear()} Elektrokomplekt LLP · Lucrum Order Automation</span><span><ShieldCheck size={13} /> Заказы поставщикам не отправляются автоматически</span></footer>
        </main>
      </div>
    </div>
  );
}

function FilterSelect({ label, value, options, onChange, optionLabel = (option: string) => option }: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  optionLabel?: (option: string) => string;
}) {
  return <label className="luc-filter"><span>{label}</span><div><select value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option value={option} key={option}>{optionLabel(option)}</option>)}</select><ChevronDown size={13} /></div></label>;
}

function Metric({ label, value, sub, icon, tone }: { label: string; value: string; sub: string; icon: ReactNode; tone: string }) {
  return <Card className="luc-metric"><div className={`luc-metric-icon ${tone}`}>{icon}</div><div className="luc-metric-copy"><span>{label}</span><b>{value}</b><small>{sub}</small></div></Card>;
}
