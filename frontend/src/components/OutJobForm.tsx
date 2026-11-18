import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Alert, Box, Button, Card, Checkbox, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, TextField, Typography } from '@mui/material'
import { api, apiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { ApiRecord } from '../types'
import { InJobQuickAddDialog } from './InJobQuickAddDialog'
import PaymentsRounded from '@mui/icons-material/PaymentsRounded'

type Customer = { id: number; name: string; mobile: string }
type Options = { customers: Customer[]; suppliers?: { id: number; name: string }[] }
type Values = Record<string, string | boolean>
const moneyFields = ['supplier_expenses', 'total_amount', 'advance', 'expenses', 'gst_percent', 'vendor_total_payment', 'vendor_advance']
const priorityChoices = ['low', 'normal', 'high', 'urgent']

function initial(row?: ApiRecord): Values {
  return {
    customer: String(row?.customer || ''),
    customer_name: String(row?.customer_name || row?.client_name || ''),
    contact_number: String(row?.contact_number || ''),
    supplier: String(row?.supplier || ''),
    vendor: String(row?.vendor || ''),
    job_type: String(row?.job_type || ''),
    supplier_expenses: String(row?.supplier_expenses ?? row?.vendor_cost ?? '0'),
    status: String(row?.status || 'pending'),
    priority: String(row?.priority || 'normal'),
    description: String(row?.description || ''),
    quantity: String(row?.quantity || 1),
    delivery_date: String(row?.delivery_date || ''),
    delivery_lp_office: Boolean(row?.delivery_lp_office),
    delivery_porter: Boolean(row?.delivery_porter),
    delivery_courier: Boolean(row?.delivery_courier),
    remarks: String(row?.remarks || ''),
    total_amount: String(row?.total_amount ?? '0'),
    advance: String(row?.advance ?? '0'),
    customer_payment_method: String(row?.customer_payment_method || row?.payment_method || 'Petty Cash'),
    expenses: String(row?.expenses ?? '0'),
    payment_status: String(row?.payment_status || 'unpaid'),
    invoice_no: String(row?.invoice_no || ''),
    gst_percent: String(row?.gst_percent ?? '18'),
    vendor_total_payment: String(row?.vendor_total_payment ?? '0'),
    vendor_advance: String(row?.vendor_advance ?? '0'),
    vendor_payment_method: String(row?.vendor_payment_method || 'Petty Cash'),
    vendor_payment_status: String(row?.vendor_payment_status || 'unpaid'),
  }
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <Box sx={{ mt: 3 }}><Typography variant="h6" fontSize={17} fontWeight={750} sx={{ mb: 1.5 }}>{title}</Typography>
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', md: 'repeat(3, 1fr)' }, gap: 1.5 }}>{children}</Box>
  </Box>
}

export function OutJobForm({ row, pending, error, onClose, onSave, dialog = false, onRecordPayment }: {
  row?: ApiRecord; pending: boolean; error: string; onClose: () => void; onSave: (payload: Record<string, unknown>) => void; dialog?: boolean;
  onRecordPayment?: (record: ApiRecord, target?: 'customer' | 'vendor') => void
}) {
  const { auth, can } = useAuth()
  const admin = Boolean(auth?.user.is_superuser)
  const [values, setValues] = useState<Values>(() => initial(row))
  const [quickCustomer, setQuickCustomer] = useState(false)
  const [createdCustomer, setCreatedCustomer] = useState<Customer | null>(null)
  const [validation, setValidation] = useState('')
  const options = useQuery({ queryKey: ['out-job-create-options'], queryFn: async () => (await api.get<Options>('/out-jobs/create-options/')).data })
  useEffect(() => { setValues(initial(row)) }, [row?.id])
  const set = (name: string, value: string | boolean) => setValues((current) => ({ ...current, [name]: value }))
  const field = (name: string, label: string, required = false, props: Record<string, unknown> = {}) => <TextField key={name} label={label} value={values[name] ?? ''} onChange={(event) => set(name, event.target.value)} required={required} fullWidth size="small" {...props} />
  const money = (name: string, label: string) => field(name, label, false, { type: 'number', slotProps: { htmlInput: { min: 0, step: '0.01' } } })
  const select = (name: string, label: string, choices: { value: string; label: string }[]) => <TextField key={name} select label={label} value={values[name]} onChange={(event) => set(name, event.target.value)} fullWidth size="small">
    {choices.map((choice) => <MenuItem key={choice.value} value={choice.value}>{choice.label}</MenuItem>)}
  </TextField>
  const checkbox = (name: string, label: string) => <FormControlLabel key={name} control={<Checkbox checked={Boolean(values[name])} onChange={(event) => set(name, event.target.checked)} />} label={label} />
  const amount = (name: string) => Number(values[name] || 0)
  const customerBalance = amount('total_amount') - amount('advance')
  const supplierBalance = amount('vendor_total_payment') - amount('vendor_advance')
  const profit = amount('total_amount') - amount('supplier_expenses') - amount('expenses')
  const paymentCompleted = values.payment_status === 'paid' || values.vendor_payment_status === 'paid'
  const cannotCancel = values.status === 'in_progress' && paymentCompleted
  const paymentLabel = (paid: number, total: number) => paid > 0 ? (paid === total ? 'Paid' : 'Partial') : 'Pending'
  const customers = [...(options.data?.customers || []), ...(createdCustomer && !options.data?.customers.some((item) => item.id === createdCustomer.id) ? [createdCustomer] : [])]
  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (admin && (customerBalance < 0 || supplierBalance < 0)) { setValidation('An advance cannot exceed its total amount.'); return }
    setValidation('')
    const payload: Record<string, unknown> = {}
    Object.entries(values).forEach(([key, value]) => {
      // Posted customer/vendor advances are ledger-backed. They must be changed
      // through the Record Payment workflow, not by saving the job form.
      if (row && ['advance', 'vendor_advance', 'payment_status', 'vendor_payment_status', 'customer_payment_method', 'vendor_payment_method'].includes(key)) return
      if (key === 'customer' || key === 'supplier') {
        if (value) payload[key] = Number(value)
        else if (row) payload[key] = null
        return
      }
      if (key === 'quantity') payload[key] = Number(value)
      else if (moneyFields.includes(key)) { if (admin || key === 'supplier_expenses') payload[key] = Number(value) }
      else if (['payment_status', 'invoice_no', 'vendor_payment_status'].includes(key)) { if (admin) payload[key] = value }
      else if (key === 'status') {
        if (row?.id && value) payload[key] = value
        /* New jobs stay pending until accepted on the Job Board. */
      }
      else if (key === 'delivery_date') { payload[key] = value ? value : null }
      else payload[key] = value
    })
    if (row && String(row?.job_number || '').startsWith('PL')) delete payload.customer
    onSave(payload)
  }

  const formBody = <>
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
    {validation && <Alert severity="error" sx={{ mb: 2 }}>{validation}</Alert>}
    {options.isError && <Alert severity="error">Could not load Out Job choices: {apiError(options.error)}</Alert>}
    {options.isLoading ? <Box sx={{ textAlign: 'center', p: 5 }}><CircularProgress /></Box> : <>
      <Section title="Job Details">
        <TextField select label="Existing Customer" value={values.customer} onChange={(event) => {
          if (event.target.value === '__add_new__') { setQuickCustomer(true); return }
          const customer = customers.find((item) => String(item.id) === event.target.value)
          setValues((current) => ({ ...current, customer: event.target.value, ...(customer ? { customer_name: customer.name, contact_number: customer.mobile } : {}) }))
        }} fullWidth size="small" disabled={Boolean(row?.pipeline_job || String(row?.job_number || '').startsWith('PL'))}>
          <MenuItem value="">Select to auto-fill</MenuItem>
          {customers.map((customer) => <MenuItem key={customer.id} value={String(customer.id)}>{customer.name}{customer.mobile ? ` (${customer.mobile})` : ''}</MenuItem>)}
          {can('customers') && <MenuItem value="__add_new__">＋ Add new customer…</MenuItem>}
        </TextField>
        {field('customer_name', 'Customer Name', true)}{field('contact_number', 'Contact Number')}
        <TextField select label="Existing Supplier" value={values.supplier} size="small" onChange={(event) => {
          const supplier = options.data?.suppliers?.find((item) => String(item.id) === event.target.value)
          setValues((current) => ({ ...current, supplier: event.target.value, vendor: supplier?.name || '' }))
        }}>
          <MenuItem value="">Enter supplier manually</MenuItem>
          {options.data?.suppliers?.map((supplier) => <MenuItem key={supplier.id} value={String(supplier.id)}>{supplier.name}</MenuItem>)}
        </TextField>
        {field('vendor', 'Supplier Name', true, { disabled: Boolean(values.supplier) })}
        {field('job_type', 'Job Type', true)}{money('supplier_expenses', 'Supplier Expenses')}
        {row?.id ? (
          <TextField select label="Status" value={values.status} onChange={(event) => set('status', event.target.value)} fullWidth size="small">
            <MenuItem value="pending">Pending</MenuItem>
            <MenuItem value="sent">Sent to vendor</MenuItem>
            <MenuItem value="in_progress">In Progress</MenuItem>
            <MenuItem value="ready">Ready</MenuItem>
            <MenuItem value="completed">Completed</MenuItem>
             <MenuItem value="cancelled" disabled={cannotCancel}>Cancelled{cannotCancel ? ' (payment completed)' : ''}</MenuItem>
          </TextField>
        ) : (
          <TextField select label="Status" value="pending" fullWidth size="small" helperText="Starts pending. Accept and start it on the Job Board; completed jobs move to Delivery.">
            <MenuItem value="pending">Pending offer</MenuItem><MenuItem value="in_progress" disabled>In Progress</MenuItem><MenuItem value="completed" disabled>Completed</MenuItem><MenuItem value="delivered" disabled>Delivered (Delivery module)</MenuItem>
          </TextField>
        )}
        {select('priority', 'Priority', priorityChoices.map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) })))}
        {field('description', 'Job Description', false, { multiline: true, minRows: 2, sx: { gridColumn: { md: 'span 2' } } })}
        {field('quantity', 'Quantity', true, { type: 'number', slotProps: { htmlInput: { min: 1 } } })}
        {field('delivery_date', 'Delivery Date', false, { type: 'date', slotProps: { inputLabel: { shrink: true } } })}
      </Section>
      <Section title="Delivery">
        <Box sx={{ gridColumn: '1 / -1' }}>{checkbox('delivery_lp_office', 'LP Office')}{checkbox('delivery_porter', 'Porter')}{checkbox('delivery_courier', 'Courier')}</Box>
        <Typography color="text.secondary" fontSize={12} sx={{ gridColumn: '1 / -1' }}>Leave all unchecked for customer pickup.</Typography>
      </Section>
      <Section title="Remarks">{field('remarks', 'Remarks', false, { multiline: true, minRows: 2, sx: { gridColumn: '1 / -1' } })}</Section>
      {admin && <>
        <Section title="Finance (Admin Only)">
          {money('total_amount', 'Total Amount')}{money('advance', 'Advance')}
          {amount('advance') > 0 && select('customer_payment_method', 'Cust. Advance Method', [
            { value: 'Petty Cash', label: '💵 Petty Cash' },
            { value: 'UPI', label: '📱 UPI / GPay / Online' },
            { value: 'Net Banking', label: '🏦 Net Banking / NEFT' },
            { value: "God's Account", label: "🙏 First Payment to God (Sacred Reserve)" },
            { value: 'Cheque', label: '📄 Cheque' },
          ])}
          <TextField label="Balance" value={customerBalance.toFixed(2)} size="small" slotProps={{ input: { readOnly: true } }} />
          {money('expenses', 'Expenses')}
          <TextField label="Profit" value={profit.toFixed(2)} size="small" slotProps={{ input: { readOnly: true } }} />
           <TextField label="Payment Status" value={paymentLabel(amount('advance'), amount('total_amount'))} slotProps={{ input: { readOnly: true } }} helperText="Calculated from recorded payments." />{field('invoice_no', 'Invoice No')}{money('gst_percent', 'GST %')}
           {row?.id && onRecordPayment && <Button type="button" variant="outlined" startIcon={<PaymentsRounded />} onClick={() => onRecordPayment(row, 'customer')} sx={{ alignSelf: 'center' }}>Record customer payment</Button>}
        </Section>
        <Section title="Supplier Payment (Admin Only)">
          {money('vendor_total_payment', 'Total Payment (to Supplier)')}{money('vendor_advance', 'Advance (to Supplier)')}
          {amount('vendor_advance') > 0 && select('vendor_payment_method', 'Supplier Advance Method', [
            { value: 'Petty Cash', label: '💵 Petty Cash' },
            { value: 'Net Banking', label: '🏦 Net Banking / Bank Transfer' },
            { value: 'UPI', label: '📱 UPI / GPay' },
            { value: 'Cheque', label: '📄 Cheque' },
          ])}
          <TextField label="Balance (Owed to Supplier)" value={supplierBalance.toFixed(2)} size="small" slotProps={{ input: { readOnly: true } }} />
           <TextField label="Supplier Payment Status" value={paymentLabel(amount('vendor_advance'), amount('vendor_total_payment'))} slotProps={{ input: { readOnly: true } }} helperText="Calculated from recorded payments." />
           {row?.id && onRecordPayment && <Button type="button" variant="outlined" startIcon={<PaymentsRounded />} onClick={() => onRecordPayment(row, 'vendor')} sx={{ alignSelf: 'center' }}>Record vendor payment</Button>}
          <Typography color="text.secondary" fontSize={12} sx={{ gridColumn: '1 / -1' }}>Supplier payment is separate from what the customer owes us.</Typography>
        </Section>
      </>}
    </>}
  </>

  const quickCustomerDialog = quickCustomer && <InJobQuickAddDialog target="customer" onClose={() => setQuickCustomer(false)} onCreated={(_, item) => {
    const customer = item as Customer
    setCreatedCustomer(customer)
    setValues((current) => ({ ...current, customer: String(customer.id), customer_name: customer.name, contact_number: customer.mobile || '' }))
    setQuickCustomer(false)
    void options.refetch()
  }} />

  if (dialog) {
    return <>
      <Dialog open fullWidth maxWidth="lg" component="form" onSubmit={submit}>
        <DialogTitle>{row?.id ? `Edit Out Job ${row.job_number || ''}` : 'New Out Job'}</DialogTitle>
        <DialogContent dividers sx={{ p: { xs: 2, md: 3 } }}>
          {formBody}
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={onClose} disabled={pending}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={pending || options.isLoading || options.isError}>
            {pending ? (row?.id ? 'Saving…' : 'Creating…') : (row?.id ? 'Save Changes' : 'Create Out Job')}
          </Button>
        </DialogActions>
      </Dialog>
      {quickCustomerDialog}
    </>
  }

  return <>
    <Card component="form" onSubmit={submit} sx={{ maxWidth: 1320, mx: 'auto' }}>
      <Box sx={{ p: { xs: 2, md: 3 } }}>
        {formBody}
      </Box>
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, p: 2, borderTop: '1px solid', borderColor: 'divider' }}>
        <Button onClick={onClose} disabled={pending}>Cancel</Button>
        <Button type="submit" variant="contained" disabled={pending || options.isLoading || options.isError}>
          {pending ? (row?.id ? 'Saving…' : 'Creating…') : (row?.id ? 'Save Changes' : 'Create Out Job')}
        </Button>
      </Box>
    </Card>
    {quickCustomerDialog}
  </>
}
