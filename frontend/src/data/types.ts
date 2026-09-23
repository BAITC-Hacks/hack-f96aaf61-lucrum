export type Urgency = 'critical' | 'soon' | 'planned';

export type OrderLine = {
  id: string;
  sku: string;
  bomId?: string;
  product: string;
  category: string;
  supplier: string;
  supplierCode: string;
  warehouse: string;
  recommendedQty: number;
  quantity: number;
  unit: string;
  urgency: Urgency;
  stock?: number;
  stockout?: boolean;
  monthlyUse: number;
  leadDays?: number;
  justification: string;
  seasonality?: string;
  moq?: number;
  status: 'pending' | 'approved';
  reviewed: boolean;
  approvedBy?: string;
  approvedAt?: string;
  managerNote?: string;
};

export type CalculationRequest = { warehouse?: string; category?: string };
export type OrderRun = { runId: string | null; createdAt?: string; lines: OrderLine[] };
export type StockRecord = { sku: string; warehouse: string; quantity: number; stockout: boolean };
export type ApprovalOptions = { approvedBy?: string; managerNote?: string };
export type ApprovalResult = {
  approved: string[];
  alreadyApproved: string[];
  approvalTimestamp?: string;
  approvedBy?: string;
};
export type ExportFilters = { date?: string; supplierCode?: string; warehouse?: string };
