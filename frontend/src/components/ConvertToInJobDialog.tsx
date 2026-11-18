import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Alert, Autocomplete, Box, Button, Card, Checkbox, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, TextField, Typography } from '@mui/material'
import AutoFixHighRounded from '@mui/icons-material/AutoFixHighRounded'
import { api, apiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { ApiRecord } from '../types'
import { InJobQuickAddDialog, type QuickAddTarget } from './InJobQuickAddDialog'

type Item = { id: number; name: string; [key: string]: unknown }
type UserItem = { id: number; username: string; first_name: string; last_name: string }
type Options = {
  customers: (Item & { mobile: string })[]
  stock_items: (Item & { category: string; gsm: number; size: string })[]
  machines: (Item & { is_default: boolean })[]
  departments: Item[]
  users: UserItem[]
  job_types: string[]
  lamination_types: string[]
  binding_methods: string[]
  custom_options: Record<string, Array<{ id: number; label: string; base_value: string }>>
  pipeline_jobs?: Array<{ id: number; job_number: string; client_name: string; contact_number: string; job_date: string; job_type: string; quantity: number; priority: string; customer: number | null }>
}
type Form = Record<string, string | boolean | number[]>
type DailyMachineSummary = { morning_count: number | null; total_clicks_today: number; current_machine_count: number | null }

// Format: designer+customername+boardtype gsm,+ss/ds+matt lami+1+3 (or _ delimited)
export function parseInJobName(jobName: string): Record<string, string> | null {
  if (!jobName || !jobName.trim()) return null
  let raw = jobName.trim().replace(/\.[a-zA-Z0-9]{2,5}$/, '')
  if (!raw.includes('_') && !raw.includes('+') && !raw.includes(',')) return null

  // Clean explanatory annotations like (for laminatin) or (sheet count)
  raw = raw.replace(/\(\s*(?:for\s+)?laminat\w*\s*\)/gi, '')
  raw = raw.replace(/\(\s*sheet\s*count\s*\)/gi, '')
  raw = raw.replace(/\(\s*sheets?\s*\)/gi, '')

  // Protect arithmetic plus like 1+3 or 1 + 3 (also 1+7-8sheet)
  const masked = raw.replace(/(\d+)\s*\+\s*(\d+)/g, (_m, g1, g2) => `${g1}@@@PLUS@@@${g2}`)

  // First split on explicit delimiters [_,+,]+
  const parts = masked.split(/[\s_,+]*[_,+][\s_,+]*/).map((p) => p.trim()).filter(Boolean)

  // Further split if a part contains both text and trailing 1+3 or sheets/nos
  const refined: string[] = []
  for (const p of parts) {
    const sub = p.split(/(?<=[a-zA-Z])\s+(?=\d+@@@PLUS@@@\d+|\d+\s*sheets?|\d+\s*nos?)/i)
    for (const s of sub) {
      const sClean = s.trim()
      if (sClean) {
        refined.push(sClean.replace(/@@@PLUS@@@/g, '+'))
      }
    }
  }

  if (refined.length < 2) return null

  const res: Record<string, string> = {}
  res.job_initials = refined[0]
  res.customer_name = refined[1]

  const remaining = refined.slice(2)
  const unclaimed: string[] = []

  for (const p of remaining) {
    // Quantity (e.g. 70nos)
    const mQty = p.match(/^(\d+)\s*nos?$/i)
    if (mQty) {
      res.quantity = mQty[1]
      continue
    }

    // Sheet count explicit (e.g. 18Sheet, 5sheets)
    const mSht = p.match(/^(\d+)\s*sheets?$/i)
    if (mSht) {
      res.sheet_count = mSht[1]
      continue
    }

    // Side mode (e.g. SS, DS, ss/ds, single side, double side)
    const mSide = p.match(/^(SS|DS|single\s*side|double\s*side|ss\/ds)$/i)
    if (mSide) {
      const val = mSide[1].toUpperCase()
      res.side_mode = val.includes('DS') && !val.includes('SS') ? 'DS' : 'SS'
      continue
    }

    // Combined colour and sheets: cmyk-8sheet, multi-8sheet, 4+4-8sheet
    const mColSht = p.match(/^(cmyk|multi|multicolou?r|4\+4|4\+0|1\+1|1\+0)-(\d+)(?:sheets?)?$/i)
    if (mColSht) {
      res.colour_spec = mColSht[1]
      res.sheet_count = mColSht[2]
      continue
    }

    // Combined breakdown and sheet count: 1+7-8sheet
    const mBdSht = p.match(/^(\d+)\+(\d+)-(\d+)(?:sheets?)?$/i)
    if (mBdSht) {
      res.sheet_count = mBdSht[3]
      continue
    }

    // Explicit colour keyword: cmyk, multi, 4+4, 4+0, 4+1
    const mColOnly = p.match(/^(cmyk|multi|multicolou?r|4\+4|4\+0|4\+1)$/i)
    if (mColOnly) {
      res.colour_spec = mColOnly[1].toUpperCase()
      continue
    }

    // Sheet count expression: 1+14, 1+3, 1+17, 27+1 (number is sheet count)
    const mCol = p.match(/^(\d+)\+(\d+)(?:\s*sheets?)?$/i)
    if (mCol) {
      const front = parseInt(mCol[1], 10)
      const back = parseInt(mCol[2], 10)
      if (!res.sheet_count) {
        res.sheet_count = String(front + back)
      }
      if (!res.side_mode) {
        res.side_mode = back > 0 ? 'DS' : 'SS'
      }
      continue
    }

    // Lamination
    const mLam = p.match(/\b(matt|gloss|velvet|thermal|sparkle|bop|bopp|lami|lamination)\b/i)
    if (mLam) {
      res.lamination_type = p
      continue
    }

    // Combined paper type and GSM with 'gsm' (e.g. 'gold met 300gsm', 'art board 300gsm', '300gsm')
    const mGsmInP = p.match(/\b(\d{2,4})\s*gsm\b/i)
    if (mGsmInP) {
      res.gsm = mGsmInP[1]
      const remainder = p.replace(/\b\d{2,4}\s*gsm\b/gi, '').trim()
      if (remainder && !res.paper_type) {
        res.paper_type = remainder
      }
      continue
    }

    // Paper words with numbers without 'gsm' (e.g. 'gold met 300', 'art board 350')
    const mNum = p.match(/\b(\d{2,4})\b/)
    if (mNum && /(gold|met|paper|board|bond|vellum|sheet|art|kraft|card)/i.test(p)) {
      res.gsm = mNum[1]
      const remainder = p.replace(/\b\d{2,4}\b/g, '').trim()
      if (remainder && !res.paper_type) {
        res.paper_type = remainder
      }
      continue
    }

    unclaimed.push(p)
  }

  for (const p of unclaimed) {
    if (!res.gsm && /^\d{2,4}$/.test(p)) {
      res.gsm = p
    } else if (!res.paper_type && /(gold|met|paper|board|bond|vellum|sheet|art|kraft|card|boardtype)/i.test(p)) {
      const pClean = p.replace(/\bgsm\b/gi, '').trim()
      res.paper_type = pClean || p
    } else if (!res.paper_type && !res.gsm) {
      res.paper_type = p
    } else if (!res.lamination_type && /none/i.test(p)) {
      res.lamination_type = 'None'
    } else if (!res.lamination_type && res.side_mode && res.colour_spec) {
      res.lamination_type = p
    } else if (!res.remarks) {
      res.remarks = p
    }
  }

  if (!res.side_mode && res.colour_spec) {
    const mSplit = res.colour_spec.match(/^(\d+)\+(\d+)$/)
    if (mSplit) {
      const back = parseInt(mSplit[2], 10)
      res.side_mode = back > 0 ? 'DS' : 'SS'
    }
  }

  return res
}

const PARSED_FIELD_LABELS: Record<string, string> = {
  job_initials: 'Designer / Initials', customer_name: 'Customer', job_type: 'Job Type', gsm: 'GSM',
  paper_type: 'Board / Paper', side_mode: 'Side', lamination_type: 'Lamination', colour_spec: 'Colour',
  sheet_count: 'Sheets', quantity: 'Quantity', stock_item: 'Stock', remarks: 'Remarks',
}
const numericFields = new Set(['gsm', 'quantity', 'sheet_count', 'wastage_count', 'total_amount', 'advance', 'expenses', 'gst_percent'])
const idFields = new Set(['pipeline_job', 'customer', 'stock_item', 'printer', 'designer', 'printing_operator', 'wastage_operator', 'everyone_in_department', 'side_option', 'payment_option'])
const addNewValue = '__add_new__'

function initialForm(row?: ApiRecord): Form {
  return {
    job_name: String(row?.job_name || ''),
    job_initials: String(row?.job_initials || ''),
    pipeline_job: String(row?.pipeline_job || ''),
    customer: String(row?.customer || ''),
    customer_name: String(row?.customer_name || row?.client_name || ''),
    contact_number: String(row?.contact_number || ''),
    reference_type: String(row?.reference_type || 'regular'),
    job_date: String(row?.job_date || new Date().toLocaleDateString('sv-SE')),
    job_type: String(row?.job_type || ''),
    file_name: String(row?.file_name || ''),
    assigned_users: Array.isArray(row?.assigned_users) ? (row.assigned_users as number[]) : [],
    everyone_in_department: String(row?.everyone_in_department || ''),
    stock_item: String(row?.stock_item || ''),
    paper_type: String(row?.paper_type || ''),
    gsm: row?.gsm != null ? String(row.gsm) : '',
    paper_size: String(row?.paper_size || ''),
    colour_spec: String(row?.colour_spec || ''),
    quantity: String(row?.quantity ?? (row ? 0 : 0)),
    side_mode: String(row?.side_mode || 'SS'),
    side_option: String(row?.side_option || ''),
    sheet_count: String(row?.sheet_count ?? '0'),
    wastage_count: String(row?.wastage_count ?? '0'),
    wastage_operator: String(row?.wastage_operator || ''),
    printer: String(row?.printer || ''),
    designer: String(row?.designer || row?.assigned_designer || ''),
    printing_operator: String(row?.printing_operator || ''),
    printing_status: String(row?.printing_status || 'pending'),
    finishing_status: String(row?.finishing_status || 'pending'),
    lamination_type: String(row?.lamination_type || 'None'),
    regular_finish: row?.regular_finish != null ? Boolean(row.regular_finish) : true,
    corner_finish: Boolean(row?.corner_finish),
    binding_method: String(row?.binding_method || 'None'),
    delivery_lp_office: Boolean(row?.delivery_lp_office),
    delivery_porter: Boolean(row?.delivery_porter),
    delivery_courier: Boolean(row?.delivery_courier),
    total_amount: String(row?.total_amount ?? '0'),
    advance: String(row?.advance ?? '0'),
    payment_method: String(row?.payment_method || 'Petty Cash'),
    expenses: String(row?.expenses ?? '0'),
    payment_status: String(row?.payment_status || 'unpaid'),
    payment_option: String(row?.payment_option || ''),
    invoice_no: String(row?.invoice_no || ''),
    gst_percent: String(row?.gst_percent ?? '18'),
    remarks: String(row?.remarks || ''),
  }
}

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => <Card variant="outlined" sx={{ mt: 2, overflow: 'hidden' }}>
  <Box sx={{ px: 2, py: 1, bgcolor: 'action.hover', borderBottom: '1px solid', borderColor: 'divider' }}>
    <Typography variant="subtitle1" fontSize={15} fontWeight={750}>{title}</Typography>
  </Box>
  <Box sx={{ p: 2, display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', md: 'repeat(3, 1fr)' }, gap: 1.5 }}>{children}</Box>
</Card>

export function ConvertToInJobDialog({ row, pending, error, page = false, standalone = false, onClose, onSave }: {
  row?: ApiRecord; pending: boolean; error: string; page?: boolean; standalone?: boolean; onClose: () => void; onSave: (data: Record<string, unknown>) => void
}) {
  const { can, canShowPayments } = useAuth()
  const [form, setForm] = useState<Form>(() => initialForm(row))
  const [quickAddTarget, setQuickAddTarget] = useState<QuickAddTarget | null>(null)
  const touched = useRef(new Set<string>())
  const isPipelineConversion = Boolean(row?.id && !standalone && String(row?.job_number || '').startsWith('PL-'))
  const options = useQuery({
    queryKey: ['in-job-form-options', isPipelineConversion ? row?.id : 'create'],
    queryFn: async () => (await api.get<Options>(isPipelineConversion ? `/pipeline-jobs/${row?.id}/in-job-options/` : '/in-jobs/create-options/')).data,
  })
  const dailyClicks = useQuery({
    queryKey: ['in-job-click-summary', form.job_date],
    enabled: Boolean(form.job_date),
    queryFn: async () => (await api.get<{ machines: DailyMachineSummary[] }>('/machine-counters/daily/', { params: { date: form.job_date } })).data,
  })
  useEffect(() => {
    const refreshChoices = () => { void options.refetch() }
    window.addEventListener('focus', refreshChoices)
    return () => window.removeEventListener('focus', refreshChoices)
  }, [options.refetch])
  useEffect(() => { setForm(initialForm(row)); touched.current.clear() }, [row?.id])
  useEffect(() => {
    const selected = options.data?.customers.find((customer) => String(customer.id) === String(row?.customer || ''))
    if (selected) setForm((current) => ({
      ...current,
      ...(!touched.current.has('customer_name') && !current.job_name && !row?.customer_name ? { customer_name: selected.name } : {}),
      ...(!touched.current.has('contact_number') && !row?.contact_number ? { contact_number: selected.mobile } : {}),
    }))
  }, [options.data, row?.customer, row?.customer_name, row?.contact_number])

  const update = (field: string, value: string | boolean | number[]) => {
    touched.current.add(field)
    setForm((current) => ({ ...current, [field]: value }))
  }
  const field = (name: string, label: string, props: Record<string, unknown> = {}) => <TextField
    key={name} label={label} value={form[name] ?? ''} onChange={(event) => update(name, event.target.value)} fullWidth size="small" {...props}
  />
  const number = (name: string, label: string, extra: Record<string, unknown> = {}) => field(name, label, { type: 'number', slotProps: { htmlInput: { min: 0, step: ['total_amount', 'advance', 'expenses', 'gst_percent'].includes(name) ? '0.01' : '1' } }, ...extra })
  const select = (name: string, label: string, items: { value: string; label: string }[], createTarget?: QuickAddTarget) => <TextField
    key={name} select label={label} value={form[name] || ''} onChange={(event) => {
      if (event.target.value === addNewValue && createTarget) setQuickAddTarget(createTarget)
      else update(name, event.target.value)
    }} fullWidth size="small"
  >{items.map((item) => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
    {createTarget && <MenuItem value={addNewValue} sx={{ fontWeight: 700, color: 'primary.main' }}>＋ Add new {label.toLowerCase()}…</MenuItem>}
  </TextField>
  const fixedSelect = (name: 'priority' | 'side_mode' | 'payment_status', optionField: string, label: string, items: { value: string; label: string }[]) => {
    const aliases = options.data?.custom_options?.[name] || []
    const value = form[optionField] ? `option:${form[optionField]}` : form[name] || ''
    return <TextField key={name} select label={label} value={value} fullWidth size="small" onChange={(event) => {
      const selected = event.target.value
      if (selected === addNewValue) { setQuickAddTarget(name); return }
      const alias = aliases.find((item) => `option:${item.id}` === selected)
      touched.current.add(name)
      touched.current.add(optionField)
      setForm((current) => ({ ...current, [name]: alias?.base_value || selected, [optionField]: alias ? String(alias.id) : '' }))
    }}>
      {items.map((item) => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
      {aliases.map((item) => <MenuItem key={item.id} value={`option:${item.id}`}>{item.label}</MenuItem>)}
      <MenuItem value={addNewValue} sx={{ fontWeight: 700, color: 'primary.main' }}>＋ Add new {label.toLowerCase()}…</MenuItem>
    </TextField>
  }
  const textChoices = (current: string, defaults: string[] = [], saved: string[] = []) =>
    [...new Set([...defaults, ...saved, current].filter(Boolean))].map((value) => ({ value, label: value }))
  const checkbox = (name: string, label: string) => <FormControlLabel key={name} control={<Checkbox checked={Boolean(form[name])} onChange={(event) => update(name, event.target.checked)} />} label={label} />
  const calculatedClicks = Number(form.sheet_count || 0) * (String(form.side_mode).toUpperCase() === 'DS' ? 2 : 1)
  const balance = Number(form.total_amount || 0) - Number(form.advance || 0)
  const profit = Number(form.total_amount || 0) - Number(form.expenses || 0)
  const parsedName = useMemo(() => !form.job_name || Boolean(parseInJobName(String(form.job_name).trim())), [form.job_name])
  const savedClickSummary = useMemo(() => (dailyClicks.data?.machines || []).reduce((summary, machine) => ({
    previous: summary.previous + Number(machine.morning_count || 0),
    current: summary.current + Number(machine.total_clicks_today || 0),
    total: summary.total + Number(machine.current_machine_count || 0),
  }), { previous: 0, current: 0, total: 0 }), [dailyClicks.data])
  const clickSummary = {
    previous: Math.max(0, Math.max(savedClickSummary.total, savedClickSummary.current) - Number(row?.click_count || 0)),
    current: calculatedClicks,
    total: Math.max(0, Math.max(savedClickSummary.total, savedClickSummary.current) - Number(row?.click_count || 0)) + calculatedClicks,
  }
  const clickNumber = (value: number) => value.toLocaleString('en-IN')

  const updateJobName = (value: string) => {
    touched.current.add('job_name')
    const parsed = parseInJobName(value)
    setForm((current) => {
      const next: Form = { ...current, job_name: value }
      if (parsed) {
        Object.entries(parsed).forEach(([key, parsedValue]) => {
          if (!touched.current.has(key)) next[key] = parsedValue
        })
        // Auto-select stock item only when not touched
        if (!touched.current.has('stock_item')) {
          if (parsed.gsm) {
            const parsedGsm = parseInt(parsed.gsm, 10)
            const matches = (options.data?.stock_items || []).filter((s) => s.gsm === parsedGsm)
            if (matches.length === 1) {
              const stock = matches[0]
              next.stock_item = String(stock.id)
              if (!touched.current.has('paper_type')) next.paper_type = stock.name
              if (!touched.current.has('paper_size')) next.paper_size = stock.size || ''
            }
          } else if (parsed.paper_type) {
            const pt = parsed.paper_type.toLowerCase()
            const matches = (options.data?.stock_items || []).filter((s) =>
              s.name.toLowerCase().includes(pt)
            )
            if (matches.length === 1) {
              const stock = matches[0]
              next.stock_item = String(stock.id)
              if (!touched.current.has('paper_size')) next.paper_size = stock.size || ''
              if (!touched.current.has('gsm') && stock.gsm) next.gsm = String(stock.gsm)
            }
          }
        }
        // Auto-select existing customer if name matches
        if (parsed.customer_name && !touched.current.has('customer')) {
          const matchCust = (options.data?.customers || []).find((c) =>
            c.name.trim().toLowerCase() === parsed.customer_name.trim().toLowerCase()
          )
          if (matchCust) {
            next.customer = String(matchCust.id)
            if (!touched.current.has('contact_number') && matchCust.mobile) {
              next.contact_number = matchCust.mobile
            }
          }
        }
        // Auto-select designer if initials/designer matches
        if (parsed.job_initials && !touched.current.has('designer')) {
          const init = parsed.job_initials.trim().toLowerCase()
          const matchUser = (options.data?.users || []).find((u) => {
            const un = (u.username || '').toLowerCase()
            const fn = (u.first_name || '').toLowerCase()
            const ln = (u.last_name || '').toLowerCase()
            const full = `${fn} ${ln}`.trim()
            const initials = `${fn[0] || ''}${ln[0] || ''}`.toLowerCase()
            return un === init || fn === init || ln === init || full === init || (initials && initials === init)
          })
          if (matchUser) {
            next.designer = String(matchUser.id)
          }
        }
      }
      return next
    })
  }

  const parsedFields = useMemo(() => {
    if (!form.job_name) return null
    const parsed = parseInJobName(String(form.job_name))
    if (!parsed) return null
    const fields: Record<string, string> = { ...parsed }
    if (parsed.gsm) {
      const parsedGsm = parseInt(parsed.gsm, 10)
      const stockMatches = (options.data?.stock_items || []).filter((s) => s.gsm === parsedGsm)
      if (stockMatches.length === 1) fields.stock_item = stockMatches[0].name
    } else if (parsed.paper_type) {
      const pt = parsed.paper_type.toLowerCase()
      const stockMatches = (options.data?.stock_items || []).filter((s) =>
        s.name.toLowerCase().includes(pt)
      )
      if (stockMatches.length === 1) fields.stock_item = stockMatches[0].name
    }
    return fields
  }, [form.job_name, options.data?.stock_items])
  const chooseCustomer = (id: string, created?: Item & { mobile: string }) => {
    touched.current.add('customer')
    const chosen = created || options.data?.customers.find((customer) => String(customer.id) === id)
    setForm((current) => ({
      ...current, customer: id,
      ...(!touched.current.has('customer_name') && chosen ? { customer_name: chosen.name } : {}),
      ...(!touched.current.has('contact_number') && chosen ? { contact_number: chosen.mobile } : {}),
    }))
  }
  const chooseStock = (id: string, created?: Item & { category: string; gsm: number; size: string }) => {
    touched.current.add('stock_item')
    const chosen = created || options.data?.stock_items.find((stock) => String(stock.id) === id)
    setForm((current) => ({
      ...current, stock_item: id,
      ...(!touched.current.has('paper_type') && chosen ? { paper_type: chosen.name } : {}),
      ...(!touched.current.has('gsm') && chosen ? { gsm: String(chosen.gsm ?? '') } : {}),
      ...(!touched.current.has('paper_size') && chosen ? { paper_size: chosen.size || '' } : {}),
    }))
  }
  const choosePipeline = (id: string, created?: NonNullable<Options['pipeline_jobs']>[number]) => {
    touched.current.add('pipeline_job')
    const selected = created || options.data?.pipeline_jobs?.find((pipeline) => String(pipeline.id) === id)
    setForm((current) => {
      const next: Form = { ...current, pipeline_job: id }
      if (selected) {
        const copied: Record<string, string> = {
          customer: String(selected.customer || ''), customer_name: selected.client_name,
          contact_number: selected.contact_number || '', priority: selected.priority,
          job_date: selected.job_date, job_type: selected.job_type,
          quantity: String(selected.quantity),
        }
        Object.entries(copied).forEach(([key, value]) => { if (!touched.current.has(key)) next[key] = value })
      }
      return next
    })
  }
  const onQuickAddCreated = (target: QuickAddTarget, item: ApiRecord) => {
    const id = String(item.id)
    if (target === 'customer') chooseCustomer(id, item as Item & { mobile: string })
    else if (target === 'stock_item') chooseStock(id, item as Item & { category: string; gsm: number; size: string })
    else if (target === 'pipeline_job') choosePipeline(id, item as NonNullable<Options['pipeline_jobs']>[number])
    else if (target === 'assigned_users') {
      touched.current.add('assigned_users')
      setForm((current) => ({ ...current, assigned_users: [...new Set([...(current.assigned_users as number[]), item.id])] }))
    } else if (target === 'priority' || target === 'side_mode' || target === 'payment_status') {
      const optionField = target === 'priority' ? 'priority_option' : target === 'side_mode' ? 'side_option' : 'payment_option'
      touched.current.add(target)
      touched.current.add(optionField)
      setForm((current) => ({ ...current, [target]: String(item.base_value), [optionField]: id }))
    } else if (target === 'job_type' || target === 'lamination_type' || target === 'binding_method') update(target, String(item.label))
    else update(target, id)
    setQuickAddTarget(null)
    void options.refetch()
  }
  const save = (event: React.FormEvent) => {
    event.preventDefault()
    const payload: Record<string, unknown> = {}
    Object.entries(form).forEach(([key, value]) => {
      if (key === 'everyone_in_department' && !value) return
      if (!canShowPayments && ['total_amount', 'advance', 'payment_method', 'expenses', 'payment_status', 'payment_option', 'invoice_no', 'gst_percent'].includes(key)) {
        return
      }
      if (key === 'payment_method') {
        if (!row?.id) payload['payment_method_input'] = value
        return
      }
      if (key === 'assigned_users') payload[key] = value
      else if (idFields.has(key)) {
        if (value !== '') payload[key] = Number(value)
        else if (row) payload[key] = null
      }
      else if (numericFields.has(key)) {
        if (value !== '') payload[key] = Number(value)
        else if (row) payload[key] = 0
      }
      else payload[key] = value
    })
    onSave(payload)
  }
  const userLabel = (user: UserItem) => [user.first_name, user.last_name].filter(Boolean).join(' ') || user.username
  const lookup = (items: Item[] = []) => [{ value: '', label: 'Unassigned' }, ...items.map((item) => ({ value: String(item.id), label: item.name }))]

  const contents = <>
    <DialogTitle>
      {row?.id && (String(row.job_number || '').startsWith('IN-') || standalone)
        ? `Edit In Job ${row.job_number || ''}`
        : standalone
          ? 'Add In Job'
          : `Convert ${String(row?.job_number || 'pipeline job')} to In Job`}
    </DialogTitle>
    <DialogContent dividers>
      {options.isError && <Alert severity="error" sx={{ mb: 2 }}>{apiError(options.error)}</Alert>}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {options.isLoading ? <Box sx={{ p: 4, textAlign: 'center' }}><CircularProgress /></Box> : <>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' }, gap: 1.5, mb: 2 }}>
          {[
            ['Previous Clicks', clickSummary.previous, 'Overall machine count before this job'],
            ['Current Clicks', clickSummary.current, 'This job · SS/DS calculated'],
            ['Total Clicks', clickSummary.total, 'Previous + current job clicks'],
          ].map(([label, value, helper]) => <Card key={String(label)} variant="outlined" sx={{ p: 1.5, bgcolor: '#f8fafc' }}>
            <Typography color="text.secondary" fontSize={12} fontWeight={700}>{label}</Typography>
            <Typography variant="h5" fontWeight={800}>{dailyClicks.isLoading ? '…' : clickNumber(Number(value))}</Typography>
            <Typography color="text.secondary" fontSize={11}>{helper}</Typography>
          </Card>)}
        </Box>
        <Alert severity="info" sx={{ mb: 1 }} action={<Button size="small" onClick={() => void options.refetch()}>Refresh choices</Button>}>Choose “Add new…” to create and select a choice here without leaving this job.</Alert>
        <Section title="Basic Information">
          <Box sx={{ gridColumn: { md: 'span 2' } }}>
            <TextField
              label="Job Name / Filename (paste to auto-fill)"
              value={form.job_name}
              onChange={(event) => updateJobName(event.target.value)}
              onPaste={(event) => {
                const pasted = event.clipboardData.getData('text').trim()
                event.preventDefault()
                updateJobName(pasted)
              }}
              size="small"
              fullWidth
              color={parsedFields ? 'success' : undefined}
              helperText={
                parsedFields
                  ? '✓ Auto-filled from filename — edit any field below to override'
                  : !form.job_name
                    ? 'Format: designer+customername+boardtype gsm+ss/ds+lamination+1+3 (supports + or _)'
                    : 'No pattern match — fill fields manually below'
              }
            />
            {parsedFields && (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.6, mt: 0.8 }}>
                <Chip
                  size="small"
                  icon={<AutoFixHighRounded sx={{ fontSize: '14px !important' }} />}
                  label="Auto-detected"
                  color="success"
                  variant="outlined"
                  sx={{ fontWeight: 700, fontSize: 11 }}
                />
                {Object.entries(parsedFields).map(([key, val]) => (
                  <Chip
                    key={key}
                    size="small"
                    label={`${PARSED_FIELD_LABELS[key] || key}: ${val}`}
                    variant="outlined"
                    sx={{ fontSize: 11 }}
                  />
                ))}
              </Box>
            )}
          </Box>
          <TextField select label="Existing Customer" value={form.customer} onChange={(event) => event.target.value === addNewValue ? setQuickAddTarget('customer') : chooseCustomer(event.target.value)} size="small" fullWidth><MenuItem value="">Select to auto-fill</MenuItem>{options.data?.customers.map((customer) => <MenuItem key={customer.id} value={String(customer.id)}>{customer.name}</MenuItem>)}{can('customers') && <MenuItem value={addNewValue} sx={{ fontWeight: 700, color: 'primary.main' }}>＋ Add new customer…</MenuItem>}</TextField>
          {select('reference_type', 'Job Reference', [
            { value: 'regular', label: 'Regular (R)' },
            { value: 'corporate', label: 'Corporate (C)' },
            { value: 'walkin', label: 'Walk-in (W)' },
          ])}
          {standalone ? <TextField select label="Link Pipeline Job (optional)" value={form.pipeline_job} onChange={(event) => event.target.value === addNewValue ? setQuickAddTarget('pipeline_job') : choosePipeline(event.target.value)} size="small" fullWidth>
            <MenuItem value="">None</MenuItem>{options.data?.pipeline_jobs?.map((pipeline) => <MenuItem key={pipeline.id} value={String(pipeline.id)}>{pipeline.job_number} — {pipeline.client_name}</MenuItem>)}
            {can('pipeline') && <MenuItem value={addNewValue} sx={{ fontWeight: 700, color: 'primary.main' }}>＋ Add new Pipeline job…</MenuItem>}
          </TextField> : <TextField label="Linked Pipeline Job" value={String(row?.job_number || row?.id || '')} size="small" fullWidth slotProps={{ input: { readOnly: true } }} />}
          {field('job_date', 'Job Date', { type: 'date', slotProps: { inputLabel: { shrink: true } } })}
          {select('job_type', 'Job Type', [{ value: '', label: 'Select job type' }, ...textChoices(String(form.job_type || ''), [], options.data?.job_types)], 'job_type')}
          {field('customer_name', 'Customer Name')}
          {field('contact_number', 'Contact Number')}
          {field('file_name', 'File Name')}
        </Section>
        <Section title="Department & Users">
          <Autocomplete multiple options={[...(options.data?.users || []), ...(can('users') ? [{ id: -1, username: '＋ Add new user…', first_name: '', last_name: '' }] : [])]} value={(options.data?.users || []).filter((user) => (form.assigned_users as number[]).includes(user.id))} getOptionLabel={userLabel} isOptionEqualToValue={(a, b) => a.id === b.id} onChange={(_, users) => {
            if (users.some((user) => user.id === -1)) setQuickAddTarget('assigned_users')
            update('assigned_users', users.filter((user) => user.id !== -1).map((user) => user.id))
          }} renderInput={(params) => <TextField {...params} label="Assign individual users" size="small" />} sx={{ gridColumn: { md: 'span 2' } }} />
          {select('everyone_in_department', 'Everyone in Department', [{ value: '', label: 'No department-wide assignment' }, ...(options.data?.departments || []).map((department) => ({ value: String(department.id), label: department.name }))], can('users') ? 'everyone_in_department' : undefined)}
          <Typography color="text.secondary" fontSize={12} sx={{ gridColumn: '1 / -1' }}>Assigned users receive an offer. Once accepted, only the accepter can view full job details and work on it. Admin access remains available.</Typography>
        </Section>
        <Section title="Printing Details">
          <TextField select label="Stock Item" value={form.stock_item} onChange={(event) => event.target.value === addNewValue ? setQuickAddTarget('stock_item') : chooseStock(event.target.value)} size="small" fullWidth><MenuItem value="">Select to auto-fill</MenuItem>{options.data?.stock_items.map((stock) => <MenuItem key={stock.id} value={String(stock.id)}>{stock.name} ({stock.category})</MenuItem>)}{can('stock') && <MenuItem value={addNewValue} sx={{ fontWeight: 700, color: 'primary.main' }}>＋ Add new stock item…</MenuItem>}</TextField>
          {field('paper_type', 'Paper Type')}{number('gsm', 'GSM')}{field('paper_size', 'Paper Size')}{number('quantity', 'Quantity')}
          {fixedSelect('side_mode', 'side_option', 'Side', [{ value: 'SS', label: 'SS' }, { value: 'DS', label: 'DS' }])}
          {number('sheet_count', 'Sheet Count')}
           <TextField label="In Job Click Count (read-only; DS counts 2 per sheet)" value={calculatedClicks} size="small" fullWidth slotProps={{ input: { readOnly: true } }} helperText="Updates automatically from sheet count and Side." />
           {number('wastage_count', 'Wastage Count')}
           {Number(form.wastage_count || 0) > 0 && select('wastage_operator', 'Wastage done by', [{ value: '', label: 'Select employee' }, ...(options.data?.users || []).map((user) => ({ value: String(user.id), label: userLabel(user) }))])}
          {field('colour_spec', 'Colour')}
          {select('printer', 'Printer', lookup(options.data?.machines), can('machine') ? 'printer' : undefined)}
          {select('designer', 'Designer', [{ value: '', label: 'Unassigned' }, ...(options.data?.users || []).map((user) => ({ value: String(user.id), label: userLabel(user) }))], can('users') ? 'designer' : undefined)}
           {select('printing_operator', 'Printing operator', [{ value: '', label: 'Unassigned' }, ...(options.data?.users || []).map((user) => ({ value: String(user.id), label: userLabel(user) }))])}
           {select('printing_status', 'Printing status', [{ value: 'pending', label: 'Pending' }, { value: 'in_progress', label: 'In progress' }, { value: 'completed', label: 'Completed' }])}
        </Section>
        <Section title="Finishing Details">
           {select('finishing_status', 'Finishing status', [{ value: 'pending', label: 'Pending' }, { value: 'in_progress', label: 'In progress' }, { value: 'completed', label: 'Completed' }])}
          {select('lamination_type', 'Lamination', textChoices(String(form.lamination_type || ''), ['None', 'Matt', 'Gloss', 'Soft Touch'], options.data?.lamination_types), 'lamination_type')}
          {select('binding_method', 'Binding', textChoices(String(form.binding_method || ''), ['None'], options.data?.binding_methods), 'binding_method')}
          <Box>{checkbox('regular_finish', 'Regular Cutting')}{checkbox('corner_finish', 'Corner Cutting')}</Box>
        </Section>
        <Section title="Delivery">
          <Box sx={{ gridColumn: '1 / -1' }}>{checkbox('delivery_lp_office', 'LP Office')}{checkbox('delivery_porter', 'Porter')}{checkbox('delivery_courier', 'Courier')}</Box>
          <Typography color="text.secondary" fontSize={12} sx={{ gridColumn: '1 / -1' }}>Leave all unchecked for customer pickup. Add delivery details in the Delivery module when the job is ready.</Typography>
        </Section>
        {canShowPayments && <Section title="Finance">
          {number('total_amount', 'Total Amount')}{number('advance', 'Advance')}
          {Number(form.advance || 0) > 0 && select('payment_method', 'Advance Method', [
            { value: 'Petty Cash', label: '💵 Petty Cash' },
            { value: 'UPI', label: '📱 UPI / GPay / Online' },
            { value: 'Net Banking', label: '🏦 Net Banking / NEFT' },
            { value: "God's Account", label: "🙏 First Payment to God (Sacred Reserve)" },
            { value: 'Cheque', label: '📄 Cheque' },
          ])}
          <TextField label="Balance" value={balance.toFixed(2)} size="small" fullWidth slotProps={{ input: { readOnly: true } }} />
          {number('expenses', 'Expenses')}
          <TextField label="Profit" value={profit.toFixed(2)} size="small" fullWidth slotProps={{ input: { readOnly: true } }} />
          <TextField label="Payment Status" value={Number(form.advance || 0) > 0 ? (balance === 0 ? 'Paid' : 'Partial') : 'Pending'} size="small" fullWidth slotProps={{ input: { readOnly: true } }} helperText="Calculated from recorded payments." />
          {field('invoice_no', 'Invoice No')}{number('gst_percent', 'GST %')}
        </Section>}
        <Section title="General Remark">{field('remarks', 'Remark', { multiline: true, minRows: 3, sx: { gridColumn: '1 / -1' } })}</Section>
      </>}
    </DialogContent>
    <DialogActions sx={{ p: 2 }}><Button onClick={onClose} disabled={pending}>Cancel</Button><Button type="submit" variant="contained" disabled={pending || options.isLoading || options.isError}>{pending ? 'Saving…' : (row?.id && (String(row.job_number || '').startsWith('IN-') || standalone)) ? 'Save Changes' : standalone ? 'Create Job' : 'Convert to In Job'}</Button></DialogActions>
  </>
  return <>
    {page
      ? <Card component="form" onSubmit={save} sx={{ maxWidth: 1320, mx: 'auto' }}>{contents}</Card>
      : <Dialog open fullWidth maxWidth="lg" component="form" onSubmit={save}>{contents}</Dialog>}
    {quickAddTarget && <InJobQuickAddDialog key={quickAddTarget} target={quickAddTarget} onClose={() => setQuickAddTarget(null)} onCreated={onQuickAddCreated} />}
  </>
}
