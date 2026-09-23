export type Urgency = 'critical' | 'soon' | 'planned';
export type OrderLine = {
  id: string; sku: string; bomId: string; product: string; category: string;
  supplier: string; warehouse: string; recommendedQty: number; quantity: number;
  unit: string; urgency: Urgency; stock: number; monthlyUse: number;
  leadDays: number; justification: string; status: 'pending' | 'approved'; reviewed: boolean;
};
export type CalculationRequest = { warehouse?: string; category?: string };
export type CalculationResponse = { calculationId: string; calculatedAt: string; lines: unknown[] };
