import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Stack, Tab, Tabs, Typography } from '@mui/material'
import ExpandMoreRounded from '@mui/icons-material/ExpandMoreRounded'
import { useLocation, useNavigate } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import { api, apiError } from '../api/client'

type JobKind = 'in-jobs' | 'out-jobs'
type Job = {
  id: number
  job_number: string
  customer_name?: string
  job_type: string
  priority: string
  priority_label?: string
  printing_status?: string
  status?: string
  accepted_by?: number | null
  work_started_at?: string | null
  contact_number?: string
  quantity?: number
  remarks?: string
  description?: string
  vendor?: string
  total_amount?: string
  job_date?: string
  delivery_date?: string
}
type BoardJob = Job & { kind: JobKind }
type AcceptedProject = { id: number; kind: 'in' | 'out'; job_number: string; project_name: string; customer_name: string; accepted_at: string | null; status: string }
type AcceptedSummary = {
  totals: { employees: number; accepted_jobs: number; in_jobs: number; out_jobs: number }
  employees: Array<{ user_id: number; employee: string; username: string; accepted_count: number; in_jobs: number; out_jobs: number; projects: AcceptedProject[] }>
}

const PAYMENT_KEYS = new Set([
  'total_amount', 'advance', 'balance', 'expenses', 'profit', 'payment_status',
  'payment_method', 'vendor_cost', 'vendor_total_payment', 'vendor_advance',
  'vendor_balance', 'vendor_payment_status', 'customer_payment_method', 'vendor_payment_method',
  'subtotal', 'gst_amount', 'grand_total', 'delivery_charges',
])

export function JobBoardPage() {
  const { auth, can, canShowPayments } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const createdOffer = (location.state as { createdOffer?: { kind: string; jobNumber: string } } | null)?.createdOffer
  const superadmin = Boolean(auth?.user.is_superuser)
  const queryClient = useQueryClient()
  const [tab, setTab] = useState(0)
  const [error, setError] = useState('')
  const kinds: JobKind[] = [can('injobs') && 'in-jobs', can('outjobs') && 'out-jobs'].filter(Boolean) as JobKind[]
  const inAvailable = useQuery({
    queryKey: ['job-board', 'in-jobs', 'available'],
    queryFn: async () => (await api.get<Job[]>('/in-jobs/available/')).data,
    enabled: can('injobs'), refetchInterval: 10_000,
  })
  const outAvailable = useQuery({
    queryKey: ['job-board', 'out-jobs', 'available'],
    queryFn: async () => (await api.get<Job[]>('/out-jobs/available/')).data,
    enabled: can('outjobs'), refetchInterval: 10_000,
  })
  const inMine = useQuery({
    queryKey: ['job-board', 'in-jobs', 'my-jobs'],
    queryFn: async () => (await api.get<Job[]>('/in-jobs/my-jobs/')).data,
    enabled: can('injobs'), refetchInterval: 10_000,
  })
  const outMine = useQuery({
    queryKey: ['job-board', 'out-jobs', 'my-jobs'],
    queryFn: async () => (await api.get<Job[]>('/out-jobs/my-jobs/')).data,
    enabled: can('outjobs'), refetchInterval: 10_000,
  })
  const teamSummary = useQuery({
    queryKey: ['job-board', 'accepted-summary'],
    queryFn: async () => (await api.get<AcceptedSummary>('/job-board/accepted-summary/')).data,
    enabled: superadmin,
    refetchInterval: 10_000,
  })
  const action = useMutation({
    mutationFn: async ({ job, verb }: { job: BoardJob; verb: 'accept' | 'start' }) => {
      await api.post(`/${job.kind}/${job.id}/${verb}/`)
    },
    onSuccess: async (_data, variables) => {
      setError('')
      if (variables.verb === 'accept') setTab(1)
      await queryClient.invalidateQueries({ queryKey: ['job-board'] })
      await queryClient.invalidateQueries({ queryKey: ['resource'] })
    },
    onError: async (reason) => {
      setError(apiError(reason))
      await queryClient.invalidateQueries({ queryKey: ['job-board'] })
    },
  })
  const available: BoardJob[] = [
    ...(inAvailable.data || []).map((job) => ({ ...job, kind: 'in-jobs' as const })),
    ...(outAvailable.data || []).map((job) => ({ ...job, kind: 'out-jobs' as const })),
  ]
  const mine: BoardJob[] = [
    ...(inMine.data || []).map((job) => ({ ...job, kind: 'in-jobs' as const })),
    ...(outMine.data || []).map((job) => ({ ...job, kind: 'out-jobs' as const })),
  ]
  const loading = kinds.some((kind) => kind === 'in-jobs' ? (tab === 1 ? inMine.isLoading : inAvailable.isLoading) : (tab === 1 ? outMine.isLoading : outAvailable.isLoading))
  const queryError = [inAvailable, outAvailable, inMine, outMine].some((query) => query.isError)
  const jobs = tab === 1 ? mine : available

  return <Box>
    <Typography variant="h4" fontWeight={800}>Job board</Typography>
    <Typography color="text.secondary" sx={{ mt: 0.5, mb: 3 }}>Open jobs show a limited preview. Accept a job to unlock its full details; it then disappears from everyone else's board.</Typography>
    {createdOffer && <Alert severity="success" sx={{ mb: 2 }} onClose={() => navigate(location.pathname, { replace: true, state: null })}>
      {createdOffer.jobNumber} was saved as an open Out Job offer. It is not assigned to a designer or staff member; eligible employees can accept it here. It appears in the Out Jobs list only after acceptance.
    </Alert>}
    <Tabs value={tab} onChange={(_event, value: number) => { setTab(value); setError('') }} sx={{ mb: 2 }}>
      <Tab label={`Available (${available.length})`} /><Tab label={`My accepted jobs (${mine.length})`} />
      {superadmin && <Tab label={`Team acceptances (${teamSummary.data?.totals.accepted_jobs ?? 0})`} />}
    </Tabs>
    {error && <Alert severity="warning" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
    {queryError && <Alert severity="error" sx={{ mb: 2 }}>Could not load some jobs. Check your connection and try again.</Alert>}
    {tab === 2 && superadmin ? <>
      {teamSummary.isError && <Alert severity="error" sx={{ mb: 2 }}>Could not load team acceptances: {apiError(teamSummary.error)}</Alert>}
      {teamSummary.isLoading ? <CircularProgress /> : teamSummary.data && <>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }, gap: 1.5, mb: 2 }}>
          {[
            ['Employees who accepted', teamSummary.data.totals.employees],
            ['Accepted projects', teamSummary.data.totals.accepted_jobs],
            ['In Jobs', teamSummary.data.totals.in_jobs],
            ['Out Jobs', teamSummary.data.totals.out_jobs],
          ].map(([label, count]) => <Card key={label} variant="outlined"><CardContent><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h4" fontWeight={800}>{count}</Typography></CardContent></Card>)}
        </Box>
        {teamSummary.data.employees.length === 0 ? <Card><CardContent><Typography color="text.secondary">No employee has accepted a job yet.</Typography></CardContent></Card> :
          <Stack spacing={1.5}>{teamSummary.data.employees.map((employee) => <Accordion key={employee.user_id} variant="outlined" disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreRounded />}><Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap"><Typography fontWeight={800}>{employee.employee}</Typography><Chip size="small" color="primary" label={`${employee.accepted_count} accepted`} /><Chip size="small" variant="outlined" label={`${employee.in_jobs} In`} /><Chip size="small" variant="outlined" label={`${employee.out_jobs} Out`} /></Stack></AccordionSummary>
            <AccordionDetails sx={{ display: 'grid', gap: 1 }}>
              {employee.projects.map((project) => <Box key={`${project.kind}-${project.id}`} sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1.5 }}>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap"><Typography fontWeight={700}>{project.job_number}</Typography><Chip size="small" label={project.kind === 'in' ? 'In Job' : 'Out Job'} /><Chip size="small" variant="outlined" label={project.status.replaceAll('_', ' ')} /></Stack>
                <Typography>{project.project_name || 'Untitled project'}</Typography>
                <Typography variant="body2" color="text.secondary">Customer: {project.customer_name || '—'} · Accepted: {project.accepted_at ? new Date(project.accepted_at).toLocaleString('en-IN') : 'Time not recorded'}</Typography>
              </Box>)}
            </AccordionDetails>
          </Accordion>)}</Stack>}
      </>}
    </> : loading ? <CircularProgress /> : jobs.length === 0 ? <Card><CardContent><Typography color="text.secondary">{tab === 1 ? 'You have not accepted a job yet.' : 'No jobs are available right now.'}</Typography></CardContent></Card> :
      <Stack spacing={1.5}>{jobs.map((job) => <Card key={`${job.kind}-${job.id}`} variant="outlined"><CardContent sx={{ display: 'flex', alignItems: { xs: 'flex-start', sm: 'center' }, justifyContent: 'space-between', flexDirection: { xs: 'column', sm: 'row' }, gap: 2 }}>
        <Box><Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap"><Typography fontWeight={800}>{job.job_number}</Typography><Chip size="small" label={job.kind === 'in-jobs' ? 'In job' : 'Out job'} /><Chip size="small" label={job.priority_label || job.priority} color={job.priority === 'high' || job.priority === 'urgent' ? 'warning' : 'default'} /></Stack>
          <Typography sx={{ mt: 0.5 }}>{job.job_type}</Typography>
          <Typography variant="body2" color="text.secondary">Status: {job.printing_status || job.status}{job.work_started_at ? ' · Work started' : ''}</Typography>
        </Box>
        {tab === 0 ?
          <Button variant="contained" disabled={action.isPending} onClick={() => action.mutate({ job, verb: 'accept' })}>Accept job</Button> :
          job.kind === 'in-jobs' && !job.work_started_at && (job.printing_status === 'pending' || job.status === 'pending' || job.status === 'sent') ?
            <Button variant="contained" disabled={action.isPending} onClick={() => action.mutate({ job, verb: 'start' })}>Start work</Button> :
            <Chip label={job.work_started_at ? 'Started' : 'Not startable'} color={job.work_started_at ? 'success' : 'default'} />}
      </CardContent>{tab === 1 ? <Accordion disableGutters elevation={0} sx={{ borderTop: '1px solid', borderColor: 'divider' }}>
        <AccordionSummary expandIcon={<ExpandMoreRounded />}><Typography fontWeight={700}>View full details</Typography></AccordionSummary>
        <AccordionDetails sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 1.5 }}>
          {Object.entries(job).filter(([key, value]) => !['id', 'kind', 'job_number', 'created_at', 'updated_at'].includes(key) && (!canShowPayments ? !PAYMENT_KEYS.has(key) : true) && value !== undefined && value !== null && value !== '').map(([key, value]) =>
            <Typography key={key} variant="body2"><Box component="span" sx={{ color: 'text.secondary' }}>{key.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())}: </Box>{Array.isArray(value) ? value.join(', ') || 'None' : typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)}</Typography>)}
        </AccordionDetails>
      </Accordion> : null}</Card>)}</Stack>}
  </Box>
}
