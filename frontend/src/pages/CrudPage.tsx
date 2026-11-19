import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useLocation, useNavigate, useSearchParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Autocomplete, Avatar, Box, Button, Card, Checkbox, Chip, CircularProgress, Dialog, DialogActions,
  DialogContent, DialogTitle, Divider, IconButton, InputAdornment, MenuItem, Table,
  TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, Tabs, Tab, TextField, Tooltip, Typography,
} from '@mui/material'
import SearchRounded from '@mui/icons-material/SearchRounded'
import EditRounded from '@mui/icons-material/EditRounded'
import InboxRounded from '@mui/icons-material/InboxRounded'
import FactoryRounded from '@mui/icons-material/FactoryRounded'
import LocalShippingRounded from '@mui/icons-material/LocalShippingRounded'
import TuneRounded from '@mui/icons-material/TuneRounded'
import PowerSettingsNewRounded from '@mui/icons-material/PowerSettingsNewRounded'
import DeleteOutlineRounded from '@mui/icons-material/DeleteOutlineRounded'
import AccountTreeRounded from '@mui/icons-material/AccountTreeRounded'
import RequestQuoteRounded from '@mui/icons-material/RequestQuoteRounded'
import Inventory2Rounded from '@mui/icons-material/Inventory2Rounded'
import PrintRounded from '@mui/icons-material/PrintRounded'
import ContentCutRounded from '@mui/icons-material/ContentCutRounded'
import FlagRounded from '@mui/icons-material/FlagRounded'
import CancelRounded from '@mui/icons-material/CancelRounded'
import PaymentsRounded from '@mui/icons-material/PaymentsRounded'
import AddRounded from '@mui/icons-material/AddRounded'
import VisibilityRounded from '@mui/icons-material/VisibilityRounded'
import SwapHorizRounded from '@mui/icons-material/SwapHorizRounded'
import HourglassTopRounded from '@mui/icons-material/HourglassTopRounded'
import CheckCircleOutlineRounded from '@mui/icons-material/CheckCircleOutlineRounded'
import ReceiptLongRounded from '@mui/icons-material/ReceiptLongRounded'
import { api, apiError } from '../api/client'
import { resources } from '../config/resources'
import type { ApiRecord, ColumnConfig, FieldConfig } from '../types'
import { PageHeader } from '../components/PageHeader'
import { RecordDialog } from '../components/RecordDialog'
import { ConvertToInJobDialog } from '../components/ConvertToInJobDialog'
import { OutJobForm } from '../components/OutJobForm'
import { RecordPaymentDialog } from '../components/RecordPaymentDialog'
import { InvoicePreviewDialog } from './InvoiceManagementPage'
import { useAuth } from '../auth/AuthContext'
import { FinanceSummary } from '../components/FinanceSummary'
import { MachineDailyOverview } from '../components/MachineDailyOverview'

const statusColors: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info' | 'primary'> = {
  completed: 'success', delivered: 'success', paid: 'success', running: 'success', ready: 'success', approved: 'success',
  urgent: 'error', cancelled: 'error', failed: 'error', breakdown: 'error',
  pending: 'warning', partial: 'warning', on_hold: 'warning', maintenance: 'warning', quoted: 'info',
  in_progress: 'primary', designing: 'primary', dispatched: 'primary', sent: 'info', high: 'error', normal: 'default', low: 'info',
}

type BulkUser = { id: number; username: string; first_name: string; last_name: string; department: number | null; department_name: string }
type BulkOptions = { users: BulkUser[]; departments: Array<{ id: number; name: string }> }
const inJobPriorityChoices = [
  { value: 'low', label: 'Low' }, { value: 'normal', label: 'Normal' },
  { value: 'high', label: 'High' }, { value: 'urgent', label: 'Urgent' },
]
const inJobStatusChoices = [
  { value: 'pending', label: 'Pending' }, { value: 'in_progress', label: 'In progress' },
  { value: 'completed', label: 'Completed' }, { value: 'on_hold', label: 'On hold' },
  { value: 'cancelled', label: 'Cancelled' },
]
const outJobPriorityChoices = [
  { value: 'low', label: 'Low' }, { value: 'normal', label: 'Normal' },
  { value: 'high', label: 'High' }, { value: 'urgent', label: 'Urgent' },
]
const outJobStatusChoices = [
  { value: 'pending', label: 'Pending' }, { value: 'sent', label: 'Sent to vendor' },
  { value: 'in_progress', label: 'In Progress' }, { value: 'ready', label: 'Ready' },
  { value: 'completed', label: 'Completed' },
]

function humanize(value: unknown) {
  return String(value ?? '—').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatDate(val: unknown) {
  if (!val) return '—'
  try {
    const d = new Date(String(val).includes('T') ? String(val) : `${String(val)}T00:00:00`)
    if (isNaN(d.getTime())) return String(val)
    const day = String(d.getDate()).padStart(2, '0')
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const year = d.getFullYear()
    return `${day}-${month}-${year}`
  } catch {
    return String(val)
  }
}

function formatMoney(val: unknown) {
  return `₹${Number(val || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const outJobPriorityBadgeColors: Record<string, { bg: string; color: string }> = {
  normal: { bg: '#0ea5e9', color: '#fff' },
  high: { bg: '#f59e0b', color: '#fff' },
  urgent: { bg: '#ef4444', color: '#fff' },
  low: { bg: '#64748b', color: '#fff' },
}

const outJobStatusBadgeColors: Record<string, { bg: string; color: string; label: string }> = {
  in_progress: { bg: '#f59e0b', color: '#fff', label: 'In Progress' },
  completed: { bg: '#10b981', color: '#fff', label: 'Completed' },
  pending: { bg: '#f97316', color: '#fff', label: 'Pending' },
  sent: { bg: '#3b82f6', color: '#fff', label: 'Sent' },
  ready: { bg: '#059669', color: '#fff', label: 'Ready' },
  cancelled: { bg: '#dc2626', color: '#fff', label: 'Cancelled' },
}

const outJobPaymentBadgeColors: Record<string, { bg: string; color: string; label: string }> = {
  paid: { bg: '#10b981', color: '#fff', label: 'Paid' },
  partial: { bg: '#f97316', color: '#fff', label: 'Partial' },
  pending: { bg: '#ef4444', color: '#fff', label: 'Pending' },
  unpaid: { bg: '#ef4444', color: '#fff', label: 'Pending' },
}

function CellValue({ value, column }: { value: unknown; column: ColumnConfig }) {
  if (column.kind === 'link' && value && typeof value === 'object') {
    const source = value as { label?: string; url?: string | null }
    return source.url ? <Button component={RouterLink} to={source.url} size="small" sx={{ textTransform: 'none' }}>{source.label}</Button> : <>{source.label || '—'}</>
  }
  if (column.kind === 'status' && value) return <Chip size="small" label={humanize(value)} color={statusColors[String(value)] || 'default'} variant="outlined" sx={{ fontWeight: 700 }} />
  if (column.kind === 'boolean') return <Chip size="small" label={value ? 'Yes' : 'No'} color={value ? 'success' : 'default'} variant="outlined" />
  if (column.kind === 'money') return <Typography fontSize={13.5} fontWeight={700}>₹{Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</Typography>
  if (column.kind === 'date' && value) return <>{new Date(`${String(value)}T00:00:00`).toLocaleDateString('en-IN')}</>
  return <>{value === null || value === undefined || value === '' ? '—' : String(value)}</>
}

const PAYMENT_COLUMN_KEYS = new Set([
  'total_amount', 'advance', 'balance', 'expenses', 'profit', 'payment_status',
  'payment_method', 'vendor_cost', 'vendor_total_payment', 'vendor_advance',
  'vendor_balance', 'vendor_payment_status', 'customer_payment_method', 'vendor_payment_method',
  'subtotal', 'gst_amount', 'grand_total', 'delivery_charges',
])

export function CrudPage({ resourceKey, embedded = false }: { resourceKey: string; embedded?: boolean }) {
  const config = resources[resourceKey]
  const navigate = useNavigate()
  const location = useLocation()
  const createdOffer = (location.state as { createdOffer?: { jobNumber: string } } | null)?.createdOffer
  const paymentNotice = (location.state as { paymentNotice?: string } | null)?.paymentNotice
  const { auth, refresh, can, canShowPayments } = useAuth()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [search, setSearch] = useState(searchParams.get('search') || '')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<ApiRecord | null>(null)
  const [saveError, setSaveError] = useState('')
  const [notice, setNotice] = useState('')
  const [paymentJob, setPaymentJob] = useState<{ job: ApiRecord; kind: 'in' | 'out'; initialTarget?: 'customer' | 'vendor' } | null>(null)
  const [workflow, setWorkflow] = useState<{ kind: string; row: ApiRecord } | null>(null)
  const [inJobTab, setInJobTab] = useState<'running' | 'cancelled'>('running')
  const [inJobPage, setInJobPage] = useState(0)
  const [selectedJobIds, setSelectedJobIds] = useState<number[]>([])
  const [departmentFilter, setDepartmentFilter] = useState('')
  const [selectedAssignees, setSelectedAssignees] = useState<BulkUser[]>([])
  const [draftPriority, setDraftPriority] = useState(searchParams.get('priority') || '')
  const [draftPrintingStatus, setDraftPrintingStatus] = useState(searchParams.get('printing_status') || '')
  const [draftFinishingStatus, setDraftFinishingStatus] = useState(searchParams.get('finishing_status') || '')
  const [outJobTab, setOutJobTab] = useState<'running' | 'cancelled'>('running')
  const [outJobPage, setOutJobPage] = useState(0)
  const [viewingOutJob, setViewingOutJob] = useState<ApiRecord | null>(null)
  const [statusModalJob, setStatusModalJob] = useState<ApiRecord | null>(null)
  const [newStatus, setNewStatus] = useState('')
  const [outJobPriority, setOutJobPriority] = useState(searchParams.get('priority') || '')
  const [outJobStatus, setOutJobStatus] = useState(searchParams.get('status') || '')
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<number | null>(null)
  const allowedFilters = ['status', 'priority', 'printing_status', 'finishing_status', 'payment_status', 'low_stock', 'job', 'account', 'category']
  const filters = Object.fromEntries([...searchParams.entries()].filter(([key]) => allowedFilters.includes(key)))
  const filterKey = JSON.stringify(filters)

  useEffect(() => setSearch(searchParams.get('search') || ''), [searchParams])
  useEffect(() => {
    setDraftPriority(searchParams.get('priority') || '')
    setDraftPrintingStatus(searchParams.get('printing_status') || '')
    setDraftFinishingStatus(searchParams.get('finishing_status') || '')
    setOutJobPriority(searchParams.get('priority') || '')
    setOutJobStatus(searchParams.get('status') || '')
  }, [searchParams])

  const query = useQuery({
    queryKey: ['resource', config.endpoint, search, filterKey],
    queryFn: async () => (await api.get<ApiRecord[]>(config.endpoint, { params: { ...filters, ...(search ? { search } : {}) } })).data,
  })
  const inJobSummary = useQuery({
    queryKey: ['in-job-summary'],
    enabled: resourceKey === 'in-jobs',
    queryFn: async () => (await api.get<ApiRecord[]>('/in-jobs/')).data,
  })
  const outJobSummary = useQuery({
    queryKey: ['out-job-summary'],
    enabled: resourceKey === 'out-jobs',
    queryFn: async () => (await api.get<ApiRecord[]>('/out-jobs/')).data,
  })
  const assignmentOptions = useQuery({
    queryKey: ['in-job-bulk-assignment-options'],
    enabled: resourceKey === 'in-jobs' && Boolean(auth?.user.is_superuser),
    queryFn: async () => (await api.get<BulkOptions>('/in-jobs/create-options/')).data,
  })
  const bulkAssign = useMutation({
    mutationFn: async () => (await api.post('/in-jobs/bulk-assign/', {
      job_ids: selectedJobIds,
      user_ids: selectedAssignees.map((user) => user.id),
    })).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['resource', config.endpoint] }),
        queryClient.invalidateQueries({ queryKey: ['in-job-summary'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
      ])
      setSelectedJobIds([])
      setSelectedAssignees([])
      setSaveError('')
      setNotice('Selected In Jobs were assigned and offered to the chosen employees.')
    },
    onError: (error) => setSaveError(apiError(error)),
  })

  const mutation = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      const hasFile = Object.values(payload).some((value) => value instanceof File || (Array.isArray(value) && value.some((item) => item instanceof File)))
      const body = hasFile ? new FormData() : payload
      if (body instanceof FormData) Object.entries(payload).forEach(([key, value]) => {
        if (Array.isArray(value)) value.forEach((item) => body.append(key, item instanceof File ? item : String(item)))
        else body.append(key, value instanceof File ? value : String(value))
      })
      const options = hasFile ? { headers: { 'Content-Type': 'multipart/form-data' } } : undefined
      return editing
        ? (await api.patch(`${config.endpoint}${editing.id}/`, body, options)).data
        : (await api.post(config.endpoint, body, options)).data
    },
    onSuccess: async (saved: ApiRecord) => {
      queryClient.invalidateQueries({ queryKey: ['resource'] })
      queryClient.invalidateQueries({ queryKey: ['form-lookups'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['machine-daily'] })
      if (['in-jobs', 'out-jobs'].includes(resourceKey) && saved.delivery_status === 'ready' && editing?.delivery_status !== 'ready') {
        setNotice('Production is complete. A Ready delivery was created automatically.')
      } else if (resourceKey === 'in-jobs' && saved.printing_status === 'completed' && saved.finishing_status === 'completed' && saved.delivery_status !== 'ready') {
        setNotice('Production is complete. Record the full customer payment to release this job to Delivery.')
      } else if (resourceKey === 'out-jobs' && saved.status === 'completed' && saved.delivery_status !== 'ready') {
        setNotice('Production is complete. Record the full customer payment to release this job to Delivery.')
      }
      if (resourceKey === 'users') await refresh()
      setDialogOpen(false)
      setEditing(null)
      setSaveError('')
    },
    onError: (error) => setSaveError(apiError(error)),
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => api.delete(`${config.endpoint}${id}/`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['resource', config.endpoint] })
      setSaveError('')
    },
    onError: (error) => setSaveError(apiError(error)),
  })

  const cancelInJobMutation = useMutation({
    mutationFn: async (id: number) => (await api.post(`/in-jobs/${id}/cancel/`)).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['resource', config.endpoint] }),
        queryClient.invalidateQueries({ queryKey: ['in-job-summary'] }),
        queryClient.invalidateQueries({ queryKey: ['job-board'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
      ])
      setNotice('In Job cancelled.')
      setSaveError('')
    },
    onError: (error) => setSaveError(apiError(error)),
  })

  const workflowMutation = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      if (!workflow) return
      const paths: Record<string, string> = {
        'stock-adjust': `/stock-items/${workflow.row.id}/adjust/`,
        'machine-status': `/machines/${workflow.row.id}/set-status/`,
      }
      return (await api.post(paths[workflow.kind], payload)).data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['resource'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      setWorkflow(null)
      setSaveError('')
    },
    onError: (error) => setSaveError(apiError(error)),
  })

  const cancelOutJobMutation = useMutation({
    mutationFn: async (id: number) => (await api.post(`/out-jobs/${id}/cancel/`)).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['resource', config.endpoint] }),
        queryClient.invalidateQueries({ queryKey: ['out-job-summary'] }),
        queryClient.invalidateQueries({ queryKey: ['job-board'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
      ])
      setNotice('Out Job cancelled.')
      setSaveError('')
    },
    onError: (error) => setSaveError(apiError(error)),
  })

  const updateStatusMutation = useMutation({
    mutationFn: async ({ id, status }: { id: number; status: string }) => (await api.patch(`/out-jobs/${id}/`, { status })).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['resource', config.endpoint] }),
        queryClient.invalidateQueries({ queryKey: ['out-job-summary'] }),
        queryClient.invalidateQueries({ queryKey: ['job-board'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
      ])
      setStatusModalJob(null)
      setNotice('Out Job status updated.')
      setSaveError('')
    },
    onError: (error) => setSaveError(apiError(error)),
  })

  const rows = useMemo(() => Array.isArray(query.data) ? query.data : [], [query.data])
  const summaryRows = useMemo(() => Array.isArray(inJobSummary.data) ? inJobSummary.data : [], [inJobSummary.data])
  const outJobSummaryRows = useMemo(() => Array.isArray(outJobSummary.data) ? outJobSummary.data : [], [outJobSummary.data])
  const inJobRows = resourceKey === 'in-jobs'
    ? rows.filter((row) => inJobTab === 'cancelled' ? row.printing_status === 'cancelled' : row.printing_status !== 'cancelled')
    : rows
  const outJobRows = resourceKey === 'out-jobs'
    ? rows.filter((row) => outJobTab === 'cancelled' ? row.status === 'cancelled' : row.status !== 'cancelled')
    : rows
  const visibleInJobRows = resourceKey === 'in-jobs' ? inJobRows.slice(inJobPage * 10, inJobPage * 10 + 10) : inJobRows
  const visibleOutJobRows = resourceKey === 'out-jobs' ? outJobRows.slice(outJobPage * 10, outJobPage * 10 + 10) : outJobRows
  const displayRows = resourceKey === 'in-jobs' ? visibleInJobRows : resourceKey === 'out-jobs' ? visibleOutJobRows : rows
  const selectableJobIds = resourceKey === 'in-jobs'
    ? visibleInJobRows.filter((row) => !row.accepted_by && row.printing_status === 'pending').map((row) => Number(row.id))
    : resourceKey === 'out-jobs'
      ? visibleOutJobRows.map((row) => Number(row.id))
      : []
  const allVisibleSelected = selectableJobIds.length > 0 && selectableJobIds.every((id) => selectedJobIds.includes(id))
  const inJobStats = {
    total: summaryRows.length,
    printing: summaryRows.filter((row) => row.printing_status === 'in_progress').length,
    finishing: summaryRows.filter((row) => row.finishing_status === 'in_progress').length,
    urgent: summaryRows.filter((row) => ['urgent', 'high'].includes(String(row.priority)) && !['completed', 'cancelled'].includes(String(row.printing_status))).length,
    cancelled: summaryRows.filter((row) => row.printing_status === 'cancelled').length,
  }
  const outJobStats = {
    total: outJobSummaryRows.length,
    inProgress: outJobSummaryRows.filter((row) => row.status === 'in_progress').length,
    completed: outJobSummaryRows.filter((row) => row.status === 'completed').length,
    delivered: outJobSummaryRows.filter((row) => row.delivery_status === 'delivered' || row.status === 'delivered').length,
    cancelled: outJobSummaryRows.filter((row) => row.status === 'cancelled').length,
    running: outJobSummaryRows.filter((row) => row.status !== 'cancelled').length,
  }
  const baseColumns = auth?.user.is_superuser && resourceKey === 'out-jobs'
    ? [...config.columns, { key: 'created_by_display', label: 'Created by' }, { key: 'accepted_by_display', label: 'Accepted by' }]
    : config.columns
  const columns = useMemo(() => {
    if (canShowPayments) return baseColumns
    return baseColumns.filter((column) => !PAYMENT_COLUMN_KEYS.has(column.key))
  }, [baseColumns, canShowPayments])
  const editFields = useMemo(() => {
    let fields = config.fields
    if (resourceKey === 'out-jobs' && !auth?.user.is_superuser) {
      fields = fields.filter((field) => !['total_amount', 'vendor_total_payment', 'expenses'].includes(field.name))
    }
    if (!canShowPayments) {
      fields = fields.filter((field) => !PAYMENT_COLUMN_KEYS.has(field.name))
    }
    return fields
  }, [resourceKey, auth?.user.is_superuser, canShowPayments, config.fields])
  const openCreate = () => navigate(`/${resourceKey}/new`)
  const applyInJobFilters = () => {
    const next = new URLSearchParams(searchParams)
    if (search) next.set('search', search); else next.delete('search')
    for (const [key, value] of [['priority', draftPriority], ['printing_status', draftPrintingStatus], ['finishing_status', draftFinishingStatus]]) {
      if (value) next.set(key, value); else next.delete(key)
    }
    setSearchParams(next)
    setInJobPage(0)
    setSelectedJobIds([])
  }
  const applyOutJobFilters = () => {
    const next = new URLSearchParams(searchParams)
    if (search) next.set('search', search); else next.delete('search')
    for (const [key, value] of [['priority', outJobPriority], ['status', outJobStatus]]) {
      if (value) next.set(key, value); else next.delete(key)
    }
    setSearchParams(next)
    setOutJobPage(0)
    setSelectedJobIds([])
  }
  const openEdit = (row: ApiRecord) => { if (resourceKey === 'quotations') { navigate(`/quotations/${row.id}/edit`); return }; setEditing(row); setSaveError(''); setDialogOpen(true) }
  const workflowDefinitions: Record<string, { title: string; fields: FieldConfig[] }> = workflow ? {
    'stock-adjust': { title: `Adjust ${String(workflow.row.name)}`, fields: [
      { name: 'movement_type', label: 'Movement type', type: 'select' as const, required: true, options: [
        { label: 'Stock in', value: 'in' }, { label: 'Stock out', value: 'out' },
        { label: 'Set verified balance', value: 'adjustment' }, { label: 'Wastage', value: 'wastage' },
      ] },
      { name: 'quantity', label: 'Quantity', type: 'number' as const, required: true },
      { name: 'reason', label: 'Reason', required: true }, { name: 'in_job', label: 'In job ID', type: 'number' as const },
      { name: 'out_job', label: 'Out job ID', type: 'number' as const },
    ] },
    'machine-status': { title: `Change status: ${String(workflow.row.name)}`, fields: [
      { name: 'status', label: 'New status', type: 'select' as const, required: true, options: [
        { label: 'Running', value: 'running' }, { label: 'Stopped', value: 'stopped' },
        { label: 'Breakdown', value: 'breakdown' }, { label: 'Maintenance', value: 'maintenance' },
      ] }, { name: 'reason', label: 'Reason' },
    ] },
  } : {}
  const workflowDefinition = workflow ? workflowDefinitions[workflow.kind] : null

  return (
    <>
      {!embedded && <PageHeader title={resourceKey === 'machines' ? 'Machine Counter' : config.title} description={config.description} actionLabel={config.readOnly || ['in-jobs', 'out-jobs'].includes(resourceKey) ? undefined : `New ${config.singular}`} onAction={openCreate} />}
      {resourceKey === 'machines' && <MachineDailyOverview />}
      {resourceKey === 'in-jobs' && <>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', md: 'repeat(4, minmax(0, 1fr))' }, gap: 1.5, mb: 2 }}>
          {[
            { label: 'Total Jobs', value: inJobStats.total, icon: Inventory2Rounded, tone: '#6554e8' },
            { label: 'Printing', value: inJobStats.printing, icon: PrintRounded, tone: '#1596a8' },
            { label: 'Finishing', value: inJobStats.finishing, icon: ContentCutRounded, tone: '#df8a2e' },
            { label: 'Urgent / High Open', value: inJobStats.urgent, icon: FlagRounded, tone: '#d95667' },
          ].map((item) => {
            const Icon = item.icon
            return <Card key={item.label} sx={{ p: 1.5, display: 'flex', alignItems: 'center', gap: 1.3 }}>
              <Box sx={{ width: 38, height: 38, borderRadius: '50%', bgcolor: `${item.tone}18`, color: item.tone, display: 'grid', placeItems: 'center' }}><Icon fontSize="small" /></Box>
              <Box><Typography variant="h6" fontWeight={800} lineHeight={1.1}>{inJobSummary.isLoading ? '—' : item.value}</Typography><Typography fontSize={11} color="text.secondary" textTransform="uppercase">{item.label}</Typography></Box>
            </Card>
          })}
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
          <Tabs value={inJobTab} onChange={(_, value: 'running' | 'cancelled') => { setInJobTab(value); setInJobPage(0); setSelectedJobIds([]) }} aria-label="In Job status tabs">
            <Tab value="running" label={<Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>Running <Chip size="small" color="primary" label={Math.max(inJobStats.total - inJobStats.cancelled, 0)} /></Box>} />
            <Tab value="cancelled" label={<Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>Cancelled <Chip size="small" label={inJobStats.cancelled} /></Box>} />
          </Tabs>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            {can('delivery') && <Button component={RouterLink} to="/deliveries" variant="outlined" color="success">Completed Jobs → Delivery</Button>}
            <Button variant="contained" onClick={openCreate}>＋ Add In Job</Button>
          </Box>
        </Box>
        <Card sx={{ p: 1.5, mb: 2, display: 'grid', gridTemplateColumns: { xs: '1fr', md: '2fr 1fr 1fr 1fr auto' }, gap: 1.25, alignItems: 'center' }}>
          <TextField label="Search" placeholder="Job no., customer, job type, designer, machine..." size="small" value={search} onChange={(event) => { setSearch(event.target.value); setInJobPage(0) }} />
          <TextField select label="Priority" size="small" value={draftPriority} onChange={(event) => setDraftPriority(event.target.value)}><MenuItem value="">All</MenuItem>{inJobPriorityChoices.map((choice) => <MenuItem key={choice.value} value={choice.value}>{choice.label}</MenuItem>)}</TextField>
          <TextField select label="Printing Status" size="small" value={draftPrintingStatus} onChange={(event) => setDraftPrintingStatus(event.target.value)}><MenuItem value="">All</MenuItem>{inJobStatusChoices.map((choice) => <MenuItem key={choice.value} value={choice.value}>{choice.label}</MenuItem>)}</TextField>
          <TextField select label="Finishing Status" size="small" value={draftFinishingStatus} onChange={(event) => setDraftFinishingStatus(event.target.value)}><MenuItem value="">All</MenuItem>{inJobStatusChoices.map((choice) => <MenuItem key={choice.value} value={choice.value}>{choice.label}</MenuItem>)}</TextField>
          <Button variant="contained" onClick={applyInJobFilters}>Filter</Button>
        </Card>
      </>}
      {resourceKey === 'out-jobs' && <>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', md: 'repeat(4, minmax(0, 1fr))' }, gap: 1.5, mb: 2 }}>
          {[
            { label: 'TOTAL JOBS', value: outJobStats.total, icon: Inventory2Rounded, tone: '#6554e8', bg: '#f3f0ff' },
            { label: 'IN PROGRESS', value: outJobStats.inProgress, icon: HourglassTopRounded, tone: '#df8a2e', bg: '#fef3c7' },
            { label: 'COMPLETED', value: outJobStats.completed, icon: CheckCircleOutlineRounded, tone: '#10b981', bg: '#dcfce7' },
            { label: 'DELIVERED', value: outJobStats.delivered, icon: LocalShippingRounded, tone: '#06b6d4', bg: '#e0f2fe' },
          ].map((item) => {
            const Icon = item.icon
            return (
              <Card key={item.label} sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 2, borderRadius: 2 }}>
                <Box sx={{ width: 44, height: 44, borderRadius: '50%', bgcolor: item.bg, color: item.tone, display: 'grid', placeItems: 'center' }}>
                  <Icon fontSize="medium" />
                </Box>
                <Box>
                  <Typography variant="h5" fontWeight={800} lineHeight={1.1}>
                    {outJobSummary.isLoading ? '—' : item.value}
                  </Typography>
                  <Typography fontSize={11} fontWeight={700} color="text.secondary" letterSpacing="0.04em">
                    {item.label}
                  </Typography>
                </Box>
              </Card>
            )
          })}
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap', mb: 2 }}>
          <Tabs value={outJobTab} onChange={(_, value: 'running' | 'cancelled') => { setOutJobTab(value); setOutJobPage(0); setSelectedJobIds([]) }} aria-label="Out Job status tabs">
            <Tab value="running" label={<Box sx={{ display: 'flex', gap: 1, alignItems: 'center', fontWeight: 700 }}>Running <Chip size="small" color="primary" label={outJobStats.running} sx={{ height: 20, fontSize: 11, fontWeight: 700 }} /></Box>} />
            <Tab value="cancelled" label={<Box sx={{ display: 'flex', gap: 1, alignItems: 'center', fontWeight: 700 }}>Cancelled <Chip size="small" label={outJobStats.cancelled} sx={{ height: 20, fontSize: 11, fontWeight: 700 }} /></Box>} />
          </Tabs>
          <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center', flexWrap: 'wrap' }}>
            {can('delivery') && (
              <Button
                component={RouterLink}
                to="/deliveries"
                variant="outlined"
                color="success"
                startIcon={<LocalShippingRounded />}
                sx={{ borderRadius: 2, textTransform: 'none', fontWeight: 700, borderColor: '#10b981', color: '#059669', '&:hover': { borderColor: '#059669', bgcolor: '#ecfdf5' } }}
              >
                Completed Jobs → Delivery
              </Button>
            )}
            <Button
              variant="contained"
              onClick={openCreate}
              startIcon={<AddRounded />}
              sx={{ borderRadius: 2, textTransform: 'none', fontWeight: 700, bgcolor: '#4f46e5', '&:hover': { bgcolor: '#4338ca' } }}
            >
              Add Out Job
            </Button>
          </Box>
        </Box>
        <Card sx={{ p: 2, mb: 2.5, display: 'grid', gridTemplateColumns: { xs: '1fr', md: '2.5fr 1fr 1fr auto' }, gap: 1.5, alignItems: 'center', borderRadius: 2 }}>
          <TextField
            label="Search"
            placeholder="Job No, Customer, Vendor..."
            size="small"
            value={search}
            onChange={(event) => { setSearch(event.target.value); setOutJobPage(0) }}
          />
          <TextField select label="Priority" size="small" value={outJobPriority} onChange={(event) => setOutJobPriority(event.target.value)}>
            <MenuItem value="">All</MenuItem>
            {outJobPriorityChoices.map((choice) => <MenuItem key={choice.value} value={choice.value}>{choice.label}</MenuItem>)}
          </TextField>
          <TextField select label="Status" size="small" value={outJobStatus} onChange={(event) => setOutJobStatus(event.target.value)}>
            <MenuItem value="">All</MenuItem>
            {outJobStatusChoices.map((choice) => <MenuItem key={choice.value} value={choice.value}>{choice.label}</MenuItem>)}
          </TextField>
          <Button
            variant="contained"
            startIcon={<SearchRounded />}
            onClick={applyOutJobFilters}
            sx={{ bgcolor: '#4f46e5', '&:hover': { bgcolor: '#4338ca' }, textTransform: 'none', fontWeight: 700, px: 3, height: 40, borderRadius: 1.5 }}
          >
            Filter
          </Button>
        </Card>
      </>}
      {resourceKey === 'enquiries' && deleteMutation.isError && <Alert severity="error" sx={{ mb: 2 }}>{apiError(deleteMutation.error)}</Alert>}
      {resourceKey === 'finance' && <FinanceSummary />}
      {['customer-payments', 'vendor-payments'].includes(resourceKey) && <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
        {resourceKey === 'customer-payments'
          ? <Button component={RouterLink} to="/vendor-payments">Open Supplier Payments</Button>
          : <Button component={RouterLink} to="/customer-payments">Open Customer Receipts</Button>}
        {can('cash') && <Button component={RouterLink} to="/cash-transactions">Open Cash Book</Button>}
        {can('accounts') && <Button component={RouterLink} to="/invoices">Open Invoices</Button>}
        <Button component={RouterLink} to="/finance">Open Finance</Button>
      </Box>}
      {resourceKey === 'out-jobs' && createdOffer && <Alert severity="success" sx={{ mb: 2 }} onClose={() => navigate(location.pathname, { replace: true, state: null })}>
        {createdOffer.jobNumber} was saved as an open offer. This list shows accepted jobs only; the offer has no staff assignment yet.
      </Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }} action={can('delivery') ? <Button color="inherit" size="small" href="/deliveries">Open deliveries</Button> : undefined}>{notice}</Alert>}
      {paymentNotice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => navigate(location.pathname, { replace: true, state: null })}>{paymentNotice}</Alert>}
      <Card id={resourceKey === 'machines' ? 'machine-management' : undefined}>
        {resourceKey === 'in-jobs' && <Box sx={{ p: 2, display: 'flex', justifyContent: 'flex-end', borderBottom: '1px solid', borderColor: 'divider' }}><Typography color="text.secondary" fontSize={13}>{inJobRows.length} jobs</Typography></Box>}
        {resourceKey === 'out-jobs' && <Box sx={{ p: 2, display: 'flex', justifyContent: 'flex-end', borderBottom: '1px solid', borderColor: 'divider' }}><Typography color="text.secondary" fontSize={13}>{outJobRows.length} jobs</Typography></Box>}
        {!['in-jobs', 'out-jobs'].includes(resourceKey) && <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
          <TextField
            placeholder={`Search ${config.title.toLowerCase()}…`}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            sx={{ width: { xs: '100%', sm: 340 } }}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchRounded fontSize="small" /></InputAdornment> } }}
          />
          <Typography color="text.secondary" fontSize={13} sx={{ display: { xs: 'none', sm: 'block' } }}>{rows.length} records</Typography>
        </Box>}
        {Object.keys(filters).length > 0 && <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1, px: 2, py: 1.2, borderBottom: '1px solid', borderColor: 'divider' }}>
          {Object.entries(filters).map(([key, value]) => <Chip key={key} size="small" label={`${key.replaceAll('_', ' ')}: ${value.replaceAll('_', ' ')}`} />)}
          <Button size="small" onClick={() => setSearchParams({})}>Clear filters</Button>
        </Box>}
        {query.isError && <Alert severity="error" sx={{ m: 2 }}>{apiError(query.error)}</Alert>}
        {query.isLoading ? (
          <Box sx={{ minHeight: 280, display: 'grid', placeItems: 'center' }}><CircularProgress size={30} /></Box>
        ) : (resourceKey === 'in-jobs' ? inJobRows.length : resourceKey === 'out-jobs' ? outJobRows.length : rows.length) === 0 ? (
          <Box sx={{ minHeight: 280, display: 'grid', placeItems: 'center', textAlign: 'center', p: 3 }}>
            <Box><InboxRounded sx={{ fontSize: 44, color: 'text.disabled' }} /><Typography fontWeight={750}>No records found</Typography><Typography color="text.secondary" fontSize={13}>Try another search or create the first record.</Typography></Box>
          </Box>
        ) : (
          <TableContainer>
            <Table sx={{ minWidth: ['in-jobs', 'out-jobs'].includes(resourceKey) ? 1200 : 800 }}>
              <TableHead>
                {resourceKey === 'out-jobs' ? (
                  <TableRow sx={{ '& th': { fontWeight: 700, color: '#475569', fontSize: 12.5, letterSpacing: '0.04em', textTransform: 'uppercase', py: 1.5 } }}>
                    <TableCell padding="checkbox">
                      <Checkbox
                        disabled={!selectableJobIds.length}
                        checked={allVisibleSelected}
                        indeterminate={selectableJobIds.some((id) => selectedJobIds.includes(id)) && !allVisibleSelected}
                        onChange={(event) => setSelectedJobIds((current) => event.target.checked ? [...new Set([...current, ...selectableJobIds])] : current.filter((id) => !selectableJobIds.includes(id)))}
                      />
                    </TableCell>
                    <TableCell>JOB NO</TableCell>
                    <TableCell>CUSTOMER</TableCell>
                    <TableCell>VENDOR</TableCell>
                    <TableCell>JOB TYPE</TableCell>
                    <TableCell>QUANTITY</TableCell>
                    <TableCell>STATUS</TableCell>
                    <TableCell>DELIVERY DATE</TableCell>
                     {canShowPayments && <>
                       <TableCell>CUSTOMER PAID</TableCell>
                       <TableCell>CUSTOMER PAYMENT</TableCell>
                       <TableCell>VENDOR PAID</TableCell>
                       <TableCell>VENDOR PAYMENT</TableCell>
                     </>}
                    <TableCell align="center">ACTIONS</TableCell>
                  </TableRow>
                ) : (
                  <TableRow>
                    {resourceKey === 'in-jobs' && auth?.user.is_superuser && <TableCell padding="checkbox"><Checkbox disabled={!selectableJobIds.length} checked={allVisibleSelected} indeterminate={selectableJobIds.some((id) => selectedJobIds.includes(id)) && !allVisibleSelected} onChange={(event) => setSelectedJobIds((current) => event.target.checked ? [...new Set([...current, ...selectableJobIds])] : current.filter((id) => !selectableJobIds.includes(id)))} /></TableCell>}
                    {columns.map((column) => <TableCell key={column.key}>{column.label}</TableCell>)}{!config.readOnly && <TableCell align="right">Action</TableCell>}
                  </TableRow>
                )}
              </TableHead>
              <TableBody>
                {resourceKey === 'out-jobs' ? (
                  displayRows.map((row) => {
                    const statusKey = String(row.status || 'pending').toLowerCase()
                    const sBadge = outJobStatusBadgeColors[statusKey] || { bg: '#64748b', color: '#fff', label: humanize(row.status) }
                    const paymentKey = String(row.payment_status || 'pending').toLowerCase()
                    const payBadge = outJobPaymentBadgeColors[paymentKey] || { bg: '#ef4444', color: '#fff', label: 'Pending' }
                     const vendorPaymentKey = String(row.vendor_payment_status || 'pending').toLowerCase()
                     const vendorPayBadge = outJobPaymentBadgeColors[vendorPaymentKey] || { bg: '#ef4444', color: '#fff', label: 'Pending' }
                    const customerName = String(row.customer_name || '—')
                    const avatarLetter = (customerName !== '—' ? customerName[0] : 'C').toUpperCase()

                    return (
                      <TableRow key={row.id} hover onDoubleClick={() => openEdit(row)} sx={{ '& td': { py: 1.5, fontSize: 13.5 }, cursor: 'pointer' }}>
                        <TableCell padding="checkbox">
                          <Checkbox
                            checked={selectedJobIds.includes(Number(row.id))}
                            onChange={(event) => setSelectedJobIds((current) => event.target.checked ? [...new Set([...current, Number(row.id)])] : current.filter((id) => id !== Number(row.id)))}
                          />
                        </TableCell>
                        <TableCell sx={{ fontWeight: 700, color: '#1e293b', whiteSpace: 'nowrap' }}>
                          {String(row.job_number || `OJ-${row.id}`)}
                        </TableCell>
                        <TableCell>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
                            <Avatar sx={{ width: 32, height: 32, bgcolor: '#ede9fe', color: '#6366f1', fontSize: 13, fontWeight: 700 }}>
                              {avatarLetter}
                            </Avatar>
                            <Typography fontSize={13.5} fontWeight={600} color="#1e293b" sx={{ whiteSpace: 'nowrap' }}>
                              {customerName}
                            </Typography>
                          </Box>
                        </TableCell>
                        <TableCell sx={{ color: '#334155', fontWeight: 500, whiteSpace: 'nowrap' }}>
                          {String(row.vendor || '—')}
                        </TableCell>
                        <TableCell sx={{ color: '#334155', fontWeight: 500, whiteSpace: 'nowrap' }}>
                          {String(row.job_type || '—')}
                        </TableCell>
                        <TableCell sx={{ fontWeight: 600, color: '#334155' }}>
                          {String(row.quantity ?? '—')}
                        </TableCell>
                        <TableCell>
                          <Chip
                            size="small"
                            label={sBadge.label}
                            sx={{
                              bgcolor: sBadge.bg,
                              color: sBadge.color,
                              fontWeight: 700,
                              fontSize: 11.5,
                              borderRadius: '12px',
                              px: 0.5,
                              height: 24,
                            }}
                          />
                        </TableCell>
                        <TableCell sx={{ color: '#475569', fontWeight: 500, whiteSpace: 'nowrap' }}>
                          {formatDate(row.delivery_date)}
                        </TableCell>
                         {canShowPayments && <>
                           <TableCell sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                             {formatMoney(row.advance)}
                           </TableCell>
                           <TableCell>
                            <Chip
                              size="small"
                              label={payBadge.label}
                              sx={{
                                bgcolor: payBadge.bg,
                                color: payBadge.color,
                                fontWeight: 700,
                                fontSize: 11.5,
                                borderRadius: '12px',
                                px: 0.5,
                                height: 24,
                              }}
                            />
                          </TableCell>
                           <TableCell sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                             {formatMoney(row.vendor_advance)}
                           </TableCell>
                           <TableCell>
                             <Chip size="small" label={vendorPayBadge.label} sx={{ bgcolor: vendorPayBadge.bg, color: vendorPayBadge.color, fontWeight: 700, fontSize: 11.5, borderRadius: '12px', px: 0.5, height: 24 }} />
                           </TableCell>
                         </>}
                        <TableCell align="center" sx={{ whiteSpace: 'nowrap' }}>
                          <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
                            <Tooltip title="View Details">
                              <IconButton
                                size="small"
                                onClick={() => setViewingOutJob(row)}
                                sx={{
                                  border: '1px solid #e2e8f0',
                                  borderRadius: 1.5,
                                  p: 0.75,
                                  color: '#64748b',
                                  '&:hover': { bgcolor: '#f8fafc', color: '#1e293b' },
                                }}
                              >
                                <VisibilityRounded fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            {Boolean(row.invoice_id) && (
                              <Tooltip title="View / Print Invoice">
                                <IconButton
                                  size="small"
                                  onClick={() => setSelectedInvoiceId(Number(row.invoice_id))}
                                  sx={{
                                    border: '1px solid #bfdbfe',
                                    borderRadius: 1.5,
                                    p: 0.75,
                                    color: 'primary.main',
                                    '&:hover': { bgcolor: '#eff6ff', color: 'primary.dark' },
                                  }}
                                >
                                  <ReceiptLongRounded fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            )}
                            <Tooltip title="Edit">
                              <IconButton
                                size="small"
                                onClick={() => openEdit(row)}
                                sx={{
                                  border: '1px solid #e2e8f0',
                                  borderRadius: 1.5,
                                  p: 0.75,
                                  color: '#64748b',
                                  '&:hover': { bgcolor: '#f8fafc', color: '#1e293b' },
                                }}
                              >
                                <EditRounded fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="Change Status">
                              <IconButton
                                size="small"
                                onClick={() => {
                                  setStatusModalJob(row)
                                  setNewStatus(String(row.status || 'pending'))
                                }}
                                sx={{
                                  border: '1px solid #e2e8f0',
                                  borderRadius: 1.5,
                                  p: 0.75,
                                  color: '#64748b',
                                  '&:hover': { bgcolor: '#f8fafc', color: '#1e293b' },
                                }}
                              >
                                <SwapHorizRounded fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="Cancel Out Job">
                              <span>
                                <IconButton
                                size="small"
                                 disabled={row.status === 'cancelled' || (row.status === 'in_progress' && (row.payment_status === 'paid' || row.vendor_payment_status === 'paid')) || cancelOutJobMutation.isPending}
                                onClick={() => {
                                  if (window.confirm(`Cancel Out Job ${String(row.job_number || '')} for ${String(row.customer_name || 'this customer')}?`)) {
                                    cancelOutJobMutation.mutate(Number(row.id))
                                  }
                                }}
                                sx={{
                                  border: '1px solid #fecaca',
                                  borderRadius: 1.5,
                                  p: 0.75,
                                  color: '#ef4444',
                                  '&:hover': { bgcolor: '#fef2f2', color: '#dc2626' },
                                  '&.Mui-disabled': { borderColor: '#f1f5f9', color: '#cbd5e1' },
                                }}
                              >
                                <CancelRounded fontSize="small" />
                              </IconButton>
                              </span>
                            </Tooltip>
                            <Tooltip title="Delete">
                              <span>
                                <IconButton
                                size="small"
                                disabled={deleteMutation.isPending}
                                onClick={() => {
                                  if (window.confirm(`Delete Out Job ${String(row.job_number || '')}? This cannot be undone.`)) {
                                    deleteMutation.mutate(Number(row.id))
                                  }
                                }}
                                sx={{
                                  border: '1px solid #fecaca',
                                  borderRadius: 1.5,
                                  p: 0.75,
                                  color: '#ef4444',
                                  '&:hover': { bgcolor: '#fef2f2', color: '#dc2626' },
                                }}
                              >
                                <DeleteOutlineRounded fontSize="small" />
                              </IconButton>
                              </span>
                            </Tooltip>
                          </Box>
                        </TableCell>
                      </TableRow>
                    )
                  })
                ) : (
                  displayRows.map((row) => (
                    <TableRow key={row.id} hover onDoubleClick={() => ['in-jobs', 'out-jobs'].includes(resourceKey) && !config.readOnly && openEdit(row)} sx={['in-jobs', 'out-jobs'].includes(resourceKey) && !config.readOnly ? { cursor: 'pointer' } : undefined}>
                      {resourceKey === 'in-jobs' && auth?.user.is_superuser && <TableCell padding="checkbox"><Checkbox checked={selectedJobIds.includes(Number(row.id))} disabled={Boolean(row.accepted_by) || row.printing_status !== 'pending'} onChange={(event) => setSelectedJobIds((current) => event.target.checked ? [...new Set([...current, Number(row.id)])] : current.filter((id) => id !== Number(row.id)))} /></TableCell>}
                      {columns.map((column, index) => <TableCell key={column.key} sx={{ fontWeight: index === 0 ? 700 : 400, whiteSpace: 'nowrap' }}><CellValue value={row[column.key]} column={column} /></TableCell>)}
                      {!config.readOnly && <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                        {resourceKey === 'pipeline' && <><Tooltip title="Convert to in job"><IconButton size="small" color="secondary" onClick={() => navigate(`/pipeline/${row.id}/convert-to-in-job`)}><FactoryRounded fontSize="small" /></IconButton></Tooltip><Tooltip title="Convert to out job"><IconButton size="small" color="primary" onClick={() => navigate(`/pipeline/${row.id}/convert-to-out-job`)}><LocalShippingRounded fontSize="small" /></IconButton></Tooltip></>}
                        {resourceKey === 'enquiries' && <>
                          {can('pipeline') && <Tooltip title="Convert to pipeline job"><IconButton size="small" color="primary" aria-label="Convert to pipeline job" onClick={() => navigate('/pipeline/new', { state: { sourceEnquiry: row } })}><AccountTreeRounded fontSize="small" /></IconButton></Tooltip>}
                          {can('quotations') && <Tooltip title="Convert to quotation"><IconButton size="small" color="secondary" aria-label="Convert to quotation" onClick={() => navigate('/quotations/new', { state: { sourceEnquiry: row } })}><RequestQuoteRounded fontSize="small" /></IconButton></Tooltip>}
                          <Tooltip title="Delete enquiry"><IconButton size="small" color="error" aria-label="Delete enquiry" disabled={deleteMutation.isPending} onClick={() => {
                            if (window.confirm(`Delete enquiry for ${String(row.customer_name || 'this customer')}? This cannot be undone.`)) deleteMutation.mutate(Number(row.id))
                          }}><DeleteOutlineRounded fontSize="small" /></IconButton></Tooltip>
                        </>}
                        {resourceKey === 'stock' && <Tooltip title="Adjust stock"><IconButton size="small" color="secondary" onClick={() => { setSaveError(''); setWorkflow({ kind: 'stock-adjust', row }) }}><TuneRounded fontSize="small" /></IconButton></Tooltip>}
                        {resourceKey === 'machines' && <Tooltip title="Change machine status"><IconButton size="small" color="secondary" onClick={() => { setSaveError(''); setWorkflow({ kind: 'machine-status', row }) }}><PowerSettingsNewRounded fontSize="small" /></IconButton></Tooltip>}
                        {resourceKey === 'in-jobs' && !['completed', 'cancelled'].includes(String(row.printing_status)) && row.finishing_status !== 'completed' && <Tooltip title="Cancel In Job"><IconButton size="small" color="error" aria-label={`Cancel In Job ${row.job_number}`} disabled={cancelInJobMutation.isPending} onClick={() => {
                          if (window.confirm(`Cancel In Job ${String(row.job_number || '')} for ${String(row.customer_name || 'this customer')}?`)) cancelInJobMutation.mutate(Number(row.id))
                        }}><CancelRounded fontSize="small" /></IconButton></Tooltip>}
                        {['in-jobs', 'out-jobs'].includes(resourceKey) && canShowPayments && (
                          <Tooltip title="Record Payment">
                            <IconButton
                              size="small"
                              color="success"
                              aria-label={`Record Payment for ${row.job_number || 'job'}`}
                              onClick={() => setPaymentJob({ job: row, kind: resourceKey === 'in-jobs' ? 'in' : 'out' })}
                            >
                              <PaymentsRounded fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                        {resourceKey === 'deliveries' && row.status !== 'delivered' && (
                          <Tooltip title="Mark Delivered & Auto-Generate Invoice">
                            <IconButton
                              size="small"
                              color="success"
                              onClick={async () => {
                                if (window.confirm(`Mark delivery for ${row.job_number || 'job'} as Delivered? This will auto-generate the invoice.`)) {
                                  try {
                                    await api.patch(`/deliveries/${row.id}/`, { status: 'delivered' })
                                    await queryClient.invalidateQueries({ queryKey: ['resource'] })
                                    await queryClient.invalidateQueries({ queryKey: ['invoices'] })
                                    setNotice('Delivery marked as Delivered. Invoice generated successfully.')
                                  } catch (err) {
                                    setSaveError(apiError(err))
                                  }
                                }
                              }}
                            >
                              <CheckCircleOutlineRounded fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                        {['in-jobs', 'deliveries'].includes(resourceKey) && Boolean(row.invoice_id) && (
                          <Tooltip title="View / Print Invoice">
                            <IconButton
                              size="small"
                              color="primary"
                              aria-label={`View Invoice for ${row.job_number || 'delivery'}`}
                              onClick={() => setSelectedInvoiceId(Number(row.invoice_id))}
                            >
                              <ReceiptLongRounded fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                        {!config.createOnly && <Tooltip title="Edit"><IconButton size="small" onClick={() => openEdit(row)}><EditRounded fontSize="small" /></IconButton></Tooltip>}
                      </TableCell>}
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
        {resourceKey === 'in-jobs' && <TablePagination component="div" count={inJobRows.length} page={Math.min(inJobPage, Math.max(0, Math.ceil(inJobRows.length / 10) - 1))} onPageChange={(_, page) => setInJobPage(page)} rowsPerPage={10} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[]} labelRowsPerPage="Jobs per page" />}
        {resourceKey === 'out-jobs' && <TablePagination component="div" count={outJobRows.length} page={Math.min(outJobPage, Math.max(0, Math.ceil(outJobRows.length / 10) - 1))} onPageChange={(_, page) => setOutJobPage(page)} rowsPerPage={10} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[]} labelRowsPerPage="Jobs per page" />}
      </Card>
      {resourceKey === 'in-jobs' && auth?.user.is_superuser && <Card sx={{ p: 2, mt: 2 }}>
        <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5 }}>Bulk Assign Selected Jobs</Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 2fr auto' }, gap: 1.5, alignItems: 'center' }}>
          <TextField select size="small" label="Filter users by department" value={departmentFilter} onChange={(event) => { setDepartmentFilter(event.target.value); setSelectedAssignees([]) }}>
            <MenuItem value="">All Departments</MenuItem>{assignmentOptions.data?.departments.map((department) => <MenuItem key={department.id} value={String(department.id)}>{department.name}</MenuItem>)}
          </TextField>
          <Autocomplete multiple options={(assignmentOptions.data?.users || []).filter((user) => !departmentFilter || String(user.department || '') === departmentFilter)} value={selectedAssignees} onChange={(_, users) => setSelectedAssignees(users)} getOptionLabel={(user) => `${[user.first_name, user.last_name].filter(Boolean).join(' ') || user.username}${user.department_name ? ` (${user.department_name})` : ''}`} isOptionEqualToValue={(a, b) => a.id === b.id} renderInput={(params) => <TextField {...params} size="small" label="Assign to employees" placeholder="Select one or more" />} />
          <Button variant="contained" disabled={!selectedJobIds.length || !selectedAssignees.length || bulkAssign.isPending} onClick={() => bulkAssign.mutate()}>Assign Selected Job(s) ({selectedJobIds.length})</Button>
        </Box>
        <Typography color="text.secondary" fontSize={12} sx={{ mt: 1 }}>Only unaccepted pending jobs can be selected. Employees receive an offer and see full details only after accepting.</Typography>
        {bulkAssign.isError && <Alert severity="error" sx={{ mt: 1 }}>{apiError(bulkAssign.error)}</Alert>}
      </Card>}
      {dialogOpen && resourceKey === 'in-jobs' ? (
        <ConvertToInJobDialog
          standalone
          row={editing || undefined}
          pending={mutation.isPending}
          error={saveError}
          onClose={() => { setDialogOpen(false); setEditing(null) }}
          onSave={(data) => mutation.mutate(data)}
        />
      ) : dialogOpen && resourceKey === 'out-jobs' ? (
        <OutJobForm
          dialog
          row={editing || undefined}
          pending={mutation.isPending}
          error={saveError}
          onClose={() => { setDialogOpen(false); setEditing(null) }}
          onSave={(data) => mutation.mutate(data)}
          onRecordPayment={canShowPayments ? (rec, target) => {
            setDialogOpen(false)
            setEditing(null)
            setPaymentJob({ job: rec, kind: 'out', initialTarget: target })
          } : undefined}
        />
      ) : (
        <RecordDialog
          open={dialogOpen}
          title={editing ? `Edit ${config.singular}` : `New ${config.singular}`}
          fields={editFields}
          record={editing}
          pending={mutation.isPending}
          error={saveError}
          onClose={() => { setDialogOpen(false); setEditing(null) }}
          onSave={(data) => mutation.mutate(data)}
          onRecordPayment={canShowPayments ? (rec, target) => {
            setDialogOpen(false)
            setEditing(null)
            setPaymentJob({ job: rec, kind: resourceKey === 'in-jobs' ? 'in' : 'out', initialTarget: target })
          } : undefined}
        />
      )}
      {workflowDefinition && <RecordDialog
        open={Boolean(workflow)}
        title={workflowDefinition.title}
        fields={[...workflowDefinition.fields]}
        pending={workflowMutation.isPending}
        error={saveError}
        onClose={() => setWorkflow(null)}
        onSave={(data) => workflowMutation.mutate(data)}
      />}
      <RecordPaymentDialog
        job={paymentJob?.job || null}
        kind={paymentJob?.kind || 'in'}
        initialTarget={paymentJob?.initialTarget}
        onClose={() => setPaymentJob(null)}
      />

      {/* View Details Dialog for Out Job */}
      <Dialog open={Boolean(viewingOutJob)} onClose={() => setViewingOutJob(null)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>Out Job Details: {String(viewingOutJob?.job_number || viewingOutJob?.id || '')}</span>
          {viewingOutJob && (
            <Chip
              size="small"
              label={humanize(viewingOutJob.status || 'pending')}
              sx={{
                bgcolor: outJobStatusBadgeColors[String(viewingOutJob.status)]?.bg || '#64748b',
                color: '#fff',
                fontWeight: 700,
              }}
            />
          )}
        </DialogTitle>
        <DialogContent dividers>
          {viewingOutJob && (<>
            <Box sx={{ display: 'grid', gap: 1.25 }}>
              <Typography variant="subtitle2" fontWeight={800}>Job Details</Typography>
              <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', sm: 'repeat(5, 1fr)' }, gap: 1, pb: 1.25 }}>
                {[
                  ['Job ID', viewingOutJob.job_number], ['Job Type', viewingOutJob.job_type], ['Quantity', viewingOutJob.quantity],
                  ['Status', humanize(viewingOutJob.status || 'pending')], ['Delivery Date', formatDate(viewingOutJob.delivery_date)],
                ].map(([label, value]) => <Box key={String(label)}><Typography variant="caption" color="text.secondary" fontWeight={700}>{String(label)}</Typography><Typography variant="body2" fontWeight={650}>{String(value ?? '—')}</Typography></Box>)}
              </Box>
              {canShowPayments && <>
                <Box sx={{ borderTop: '3px solid #1e293b', pt: 1.25 }}>
                  <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>Customer Details</Typography>
                  <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', sm: 'repeat(6, 1fr)' }, gap: 1 }}>
                    {[
                      ['Customer Name', viewingOutJob.customer_name], ['Contact', viewingOutJob.contact_number],
                      ['Payment Amount', viewingOutJob.total_amount], ['Paid Amount', viewingOutJob.advance], ['Balance Amount', viewingOutJob.balance],
                    ].map(([label, value]) => <Box key={String(label)}><Typography variant="caption" color="text.secondary" fontWeight={700}>{String(label)}</Typography><Typography variant="body2" fontWeight={650}>{['Payment Amount', 'Paid Amount', 'Balance Amount'].includes(String(label)) ? `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : String(value || '—')}</Typography></Box>)}
                    <Box><Typography variant="caption" color="text.secondary" fontWeight={700}>Payment Status</Typography><Chip size="small" label={humanize(viewingOutJob.payment_status || 'pending')} color={String(viewingOutJob.payment_status) === 'paid' ? 'success' : 'warning'} /></Box>
                  </Box>
                </Box>
                <Box sx={{ borderTop: '3px solid #1e293b', pt: 1.25 }}>
                  <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>Vendor Details</Typography>
                  <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', sm: 'repeat(6, 1fr)' }, gap: 1 }}>
                    {[
                      ['Vendor Name', viewingOutJob.vendor], ['Contact', viewingOutJob.vendor_contact],
                      ['Total Cost', viewingOutJob.vendor_total_payment || viewingOutJob.vendor_cost], ['Paid Amount', viewingOutJob.vendor_advance], ['Balance Amount', viewingOutJob.vendor_balance],
                    ].map(([label, value]) => <Box key={String(label)}><Typography variant="caption" color="text.secondary" fontWeight={700}>{String(label)}</Typography><Typography variant="body2" fontWeight={650}>{['Total Cost', 'Paid Amount', 'Balance Amount'].includes(String(label)) ? `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : String(value || '—')}</Typography></Box>)}
                    <Box><Typography variant="caption" color="text.secondary" fontWeight={700}>Payment Status</Typography><Chip size="small" label={humanize(viewingOutJob.vendor_payment_status || 'pending')} color={String(viewingOutJob.vendor_payment_status) === 'paid' ? 'success' : 'warning'} /></Box>
                  </Box>
                </Box>
              </>}
            </Box>
            <Box sx={{ display: 'none' }}>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>JOB NUMBER</Typography>
                <Typography variant="body1" fontWeight={700}>{String(viewingOutJob.job_number || '—')}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>JOB NAME / TITLE</Typography>
                <Typography variant="body1">{String(viewingOutJob.job_name || viewingOutJob.job_type_name || '—')}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>CUSTOMER</Typography>
                <Typography variant="body1" fontWeight={600}>{String(viewingOutJob.customer_name || '—')}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>VENDOR / SUPPLIER</Typography>
                <Typography variant="body1" fontWeight={600}>{String(viewingOutJob.vendor || '—')}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>PRIORITY</Typography>
                <Box sx={{ mt: 0.5 }}>
                  <Chip
                    size="small"
                    label={humanize(viewingOutJob.priority || 'normal')}
                    sx={{
                      bgcolor: outJobPriorityBadgeColors[String(viewingOutJob.priority)]?.bg || '#64748b',
                      color: '#fff',
                      fontWeight: 700,
                    }}
                  />
                </Box>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>QUANTITY</Typography>
                <Typography variant="body1" fontWeight={600}>{String(viewingOutJob.quantity ?? '—')}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>DELIVERY DATE</Typography>
                <Typography variant="body1">{formatDate(viewingOutJob.delivery_date)}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>DELIVERY STATUS</Typography>
                <Typography variant="body1">{humanize(viewingOutJob.delivery_status || 'Pending')}</Typography>
              </Box>
              {Boolean(viewingOutJob.instructions) && (
                <Box sx={{ gridColumn: '1 / -1' }}>
                  <Typography variant="caption" color="text.secondary" fontWeight={700}>INSTRUCTIONS / REMARKS</Typography>
                  <Typography variant="body2" sx={{ bgcolor: '#f8fafc', p: 1.5, borderRadius: 1.5, mt: 0.5 }}>
                    {String(viewingOutJob.instructions)}
                  </Typography>
                </Box>
              )}
              {canShowPayments && (
                <>
                  <Box sx={{ gridColumn: '1 / -1', pt: 1 }}>
                    <Divider><Typography variant="caption" fontWeight={700} color="text.secondary">FINANCIAL DETAILS</Typography></Divider>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary" fontWeight={700}>CUSTOMER TOTAL AMOUNT</Typography>
                    <Typography variant="body1" fontWeight={700} color="#059669">
                      ₹{Number(viewingOutJob.total_amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </Typography>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary" fontWeight={700}>PAYMENT STATUS</Typography>
                    <Box sx={{ mt: 0.5 }}>
                      <Chip
                        size="small"
                        label={humanize(viewingOutJob.payment_status || 'pending')}
                        sx={{
                          bgcolor: outJobPaymentBadgeColors[String(viewingOutJob.payment_status)]?.bg || '#ef4444',
                          color: '#fff',
                          fontWeight: 700,
                        }}
                      />
                    </Box>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary" fontWeight={700}>CUSTOMER ADVANCE / BALANCE</Typography>
                    <Typography variant="body2">
                      Advance: ₹{Number(viewingOutJob.advance || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })} | Balance: ₹{Number(viewingOutJob.balance || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </Typography>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary" fontWeight={700}>VENDOR TOTAL COST / PAYMENT</Typography>
                    <Typography variant="body1" fontWeight={700} color="#dc2626">
                      ₹{Number(viewingOutJob.vendor_total_payment || viewingOutJob.vendor_cost || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </Typography>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary" fontWeight={700}>VENDOR PAYMENT STATUS</Typography>
                    <Typography variant="body2">{humanize(viewingOutJob.vendor_payment_status || 'pending')}</Typography>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary" fontWeight={700}>VENDOR ADVANCE / BALANCE</Typography>
                    <Typography variant="body2">
                      Advance: ₹{Number(viewingOutJob.vendor_advance || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })} | Balance: ₹{Number(viewingOutJob.vendor_balance || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </Typography>
                  </Box>
                </>
              )}
            </Box>
          </>)}
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          {Boolean(viewingOutJob?.invoice_id) && (
            <Button
              variant="outlined"
              color="primary"
              startIcon={<ReceiptLongRounded />}
              onClick={() => setSelectedInvoiceId(Number(viewingOutJob?.invoice_id))}
            >
              View Invoice
            </Button>
          )}
          {canShowPayments && viewingOutJob && (
            <Button
              variant="outlined"
              color="success"
              startIcon={<PaymentsRounded />}
              onClick={() => {
                const job = viewingOutJob
                setViewingOutJob(null)
                setPaymentJob({ job, kind: 'out' })
              }}
            >
              Record Payment
            </Button>
          )}
          {viewingOutJob && (
            <Button
              variant="outlined"
              startIcon={<EditRounded />}
              onClick={() => {
                const job = viewingOutJob
                setViewingOutJob(null)
                openEdit(job)
              }}
            >
              Edit
            </Button>
          )}
          <Button onClick={() => setViewingOutJob(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Change Status Dialog for Out Job */}
      <Dialog open={Boolean(statusModalJob)} onClose={() => setStatusModalJob(null)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>Change Out Job Status</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Update the status for <strong>{String(statusModalJob?.job_number || `Job #${statusModalJob?.id}`)}</strong>:
          </Typography>
          <TextField
            select
            fullWidth
            size="small"
            label="Job Status"
            value={newStatus}
            onChange={(e) => setNewStatus(e.target.value)}
          >
            {outJobStatusChoices.map((choice) => (
              <MenuItem key={choice.value} value={choice.value}>
                {choice.label}
              </MenuItem>
            ))}
            <MenuItem value="cancelled">Cancelled</MenuItem>
          </TextField>
        </DialogContent>
        <DialogActions sx={{ px: 2.5, py: 1.5 }}>
          <Button onClick={() => setStatusModalJob(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={updateStatusMutation.isPending || !statusModalJob}
            onClick={() => {
              if (statusModalJob) {
                updateStatusMutation.mutate({ id: Number(statusModalJob.id), status: newStatus })
              }
            }}
            sx={{ bgcolor: '#4f46e5', '&:hover': { bgcolor: '#4338ca' } }}
          >
            Update Status
          </Button>
        </DialogActions>
      </Dialog>

      {selectedInvoiceId && (
        <InvoicePreviewDialog invoiceId={selectedInvoiceId} onClose={() => setSelectedInvoiceId(null)} />
      )}
    </>
  )
}
