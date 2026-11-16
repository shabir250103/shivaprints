export type Permissions = Record<string, boolean>

export interface AuthUser {
  id: number
  username: string
  first_name: string
  last_name: string
  email: string
  is_superuser: boolean
  show_payment_details?: boolean
  role: number | null
  role_name: string | null
  department: number | null
  department_name: string | null
  branch?: number | null
  branch_name?: string | null
}

export interface AuthPayload {
  token?: string
  user: AuthUser
  permissions: Permissions
}

export type ApiRecord = Record<string, unknown> & { id: number }

export interface FieldConfig {
  name: string
  label: string
  type?: 'text' | 'number' | 'date' | 'textarea' | 'select' | 'boolean' | 'password' | 'lookup' | 'image' | 'files'
  required?: boolean
  requiredOnCreate?: boolean
  options?: Array<{ label: string; value: string | number }>
  lookupEndpoint?: string
  lookupLabel?: string
  multiple?: boolean
  defaultValue?: string | number | boolean
  creatable?: boolean
}

export interface ColumnConfig {
  key: string
  label: string
  kind?: 'text' | 'status' | 'money' | 'date' | 'boolean' | 'link'
}

export interface ResourceConfig {
  title: string
  singular: string
  description: string
  endpoint: string
  permission: string
  columns: ColumnConfig[]
  fields: FieldConfig[]
  readOnly?: boolean
  createOnly?: boolean
}

export interface LowStockItemSummary {
  id: number
  name: string
  current_stock: number
  min_stock: number
  unit: string
  category: string
}

export interface ActionRequiredJob {
  id: number
  kind: 'in' | 'out'
  job_number: string
  customer_name: string
  total_amount: number
  balance: number
  priority: string
  reason: string
  reason_code: 'payment_blocked' | 'urgent' | 'overdue'
  date?: string
}

export interface CashAccountSummary {
  id: number
  name: string
  account_type: string
  balance: number
}

export interface TrendDaySummary {
  [key: string]: unknown
  date: string
  label: string
  in_jobs: number
  out_jobs: number
  total_jobs: number
  revenue: number
  collected: number
}

export interface StageBreakdownSummary {
  id: number
  value: number
  label: string
  color: string
}

export interface DashboardData {
  total_jobs: number
  pipeline: number
  printing: number
  completed: number
  delivered: number
  pending_payments: number
  low_stock_items: number
  low_stock_list: LowStockItemSummary[]
  action_required_jobs: ActionRequiredJob[]
  action_required_count: number
  trend_days?: TrendDaySummary[]
  stages_breakdown?: StageBreakdownSummary[]
  today_machine_clicks: number
  today_wastage: number
  urgent_jobs: number
  unread_notifications: number
  has_finance_access: boolean
  available_cash: number
  cash_accounts: CashAccountSummary[]
  total_receivables: number
  total_payables: number
  month_revenue: number
  month_collected: number
}


