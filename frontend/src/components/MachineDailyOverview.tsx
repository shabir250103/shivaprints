import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Box, Button, Card, Chip, CircularProgress, Stack, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import EditRounded from '@mui/icons-material/EditRounded'
import { api, apiError } from '../api/client'

interface MachineDailyRow {
  machine_id: number
  machine_name: string
  machine_code: string
  location: string
  operational_status: string
  status_reason: string
  last_changed: string
  counter_id: number | null
  morning_count: number | null
  ending_count: number | null
  actual_clicks: number | null
  job_clicks_booked: number
  difference: number | null
  operator_display: string
  total_clicks_today: number
  current_machine_count: number | null
  jobs_printed: number
  last_updated: string
  jobs: Array<{ id: number; job_number: string; job_name: string; machine_name: string; printing_operator: string; click_count: number; created_at: string; updated_at: string }>
}

interface CounterHistoryRow {
  id: number
  count_date: string
  machine_name: string
  operator_display: string
  morning_count: number
  ending_count: number
  actual_clicks: number
  job_clicks_booked: number
  difference: number
}

interface DailyDraft { morning: string; ending: string }
const today = () => new Date().toLocaleDateString('sv-SE')
const number = (value: number | null | undefined) => value == null ? '—' : Number(value).toLocaleString('en-IN')
const dateLabel = (value?: string | null) => value ? new Date(value).toLocaleDateString('en-IN') : '—'
const dateTimeLabel = (value?: string | null) => value ? new Date(value).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' }) : '—'

export function MachineDailyOverview() {
  const [date, setDate] = useState(today)
  const [drafts, setDrafts] = useState<Record<number, DailyDraft>>({})
  const [error, setError] = useState('')
  const queryClient = useQueryClient()
  const daily = useQuery({
    queryKey: ['machine-daily', date],
    queryFn: async () => (await api.get<{ date: string; machines: MachineDailyRow[] }>('/machine-counters/daily/', { params: { date } })).data,
    refetchInterval: 15_000,
  })
  const history = useQuery({
    queryKey: ['machine-counter-history'],
    queryFn: async () => (await api.get<CounterHistoryRow[]>('/machine-counters/')).data,
  })
  const save = useMutation({
    mutationFn: async ({ row, values }: { row: MachineDailyRow; values: DailyDraft }) => {
      const payload = { machine: row.machine_id, count_date: date, morning_count: Number(values.morning), ending_count: Number(values.ending) }
      if (row.counter_id) return api.patch(`/machine-counters/${row.counter_id}/`, payload)
      return api.post('/machine-counters/', payload)
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['machine-daily', date] }),
        queryClient.invalidateQueries({ queryKey: ['machine-counter-history'] }),
        queryClient.invalidateQueries({ queryKey: ['resource', '/machine-counters/'] }),
      ])
      setError('')
    },
    onError: (reason) => setError(apiError(reason)),
  })
  const rowDraft = (row: MachineDailyRow): DailyDraft => drafts[row.machine_id] || {
    morning: row.morning_count == null ? '' : String(row.morning_count),
    ending: row.ending_count == null ? '' : String(row.ending_count),
  }
  const updateDraft = (row: MachineDailyRow, key: keyof DailyDraft, value: string) => {
    const current = rowDraft(row)
    setDrafts((previous) => ({ ...previous, [row.machine_id]: { ...current, [key]: value } }))
  }
  const saveable = (row: MachineDailyRow) => {
    const values = rowDraft(row)
    return values.morning !== '' && values.ending !== '' && Number(values.ending) >= Number(values.morning)
  }
  const machines = daily.data?.machines || []
  const countersRecorded = machines.some((row) => row.counter_id !== null)
  const recent = (history.data || []).slice(0, 30)

  return <Stack spacing={2} sx={{ mb: 3 }}>
    <Card sx={{ overflow: 'hidden' }}>
      <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Typography fontWeight={800}>Printer Status</Typography>
        <Button size="small" startIcon={<EditRounded />} onClick={() => document.getElementById('machine-management')?.scrollIntoView({ behavior: 'smooth' })}>Manage Machines</Button>
      </Box>
      <TableContainer><Table size="small" sx={{ minWidth: 620 }}>
        <TableHead><TableRow><TableCell>Machine</TableCell><TableCell>Status</TableCell><TableCell>Reason</TableCell><TableCell>Last changed</TableCell></TableRow></TableHead>
        <TableBody>{daily.isLoading ? <TableRow><TableCell colSpan={4} align="center"><CircularProgress size={22} /></TableCell></TableRow> : machines.map((row) => <TableRow key={row.machine_id} hover>
          <TableCell><Typography fontWeight={700}>{row.machine_name}</Typography><Typography color="text.secondary" fontSize={12}>({row.machine_code})</Typography></TableCell>
          <TableCell><Chip size="small" label={row.operational_status.replaceAll('_', ' ')} color={row.operational_status === 'running' ? 'success' : row.operational_status === 'breakdown' ? 'error' : 'default'} /></TableCell>
          <TableCell>{row.status_reason || '—'}</TableCell><TableCell sx={{ whiteSpace: 'nowrap' }}>{dateTimeLabel(row.last_changed)}</TableCell>
        </TableRow>)}
          {!daily.isLoading && machines.length === 0 && <TableRow><TableCell colSpan={4} align="center">No active machines found.</TableCell></TableRow>}
        </TableBody>
      </Table></TableContainer>
    </Card>
    {daily.isError && <Alert severity="error">{apiError(daily.error)}</Alert>}

    <Card sx={{ overflow: 'hidden' }}>
      <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap', borderBottom: '1px solid', borderColor: 'divider' }}>
      <Box><Typography fontWeight={800}>Today's Machine Usage vs. Overall Clicks</Typography><Typography color="text.secondary" fontSize={12}>Overall clicks update from all In Jobs for the selected date and machine.</Typography></Box>
        <TextField label="Date" type="date" size="small" value={date} onChange={(event) => { setDate(event.target.value); setDrafts({}); setError('') }} slotProps={{ inputLabel: { shrink: true } }} />
      </Box>
      {!countersRecorded && !daily.isLoading && <Typography color="text.secondary" fontSize={13} textAlign="center" sx={{ py: 1 }}>No machine counters recorded for this date. In Job clicks are still shown below.</Typography>}
      {error && <Alert severity="error" sx={{ m: 1.5 }}>{error}</Alert>}
      <TableContainer><Table size="small" sx={{ minWidth: 800 }}>
        <TableHead><TableRow><TableCell>Machine</TableCell><TableCell>Operator</TableCell><TableCell align="right">Morning</TableCell><TableCell align="right">Ending</TableCell><TableCell align="right">Clicks today</TableCell><TableCell align="right">Current count</TableCell><TableCell align="right">Jobs printed</TableCell></TableRow></TableHead>
        <TableBody>{machines.map((row) => <TableRow key={row.machine_id} hover>
          <TableCell>{row.machine_name}</TableCell><TableCell>{row.operator_display || '—'}</TableCell>
          <TableCell align="right">{number(row.morning_count)}</TableCell><TableCell align="right">{number(row.ending_count)}</TableCell>
          <TableCell align="right" sx={{ fontWeight: 800 }}>{number(row.total_clicks_today)}</TableCell><TableCell align="right" sx={{ fontWeight: 800 }}>{number(row.current_machine_count)}</TableCell><TableCell align="right">{row.jobs_printed}</TableCell>
        </TableRow>)}
          {!daily.isLoading && machines.length === 0 && <TableRow><TableCell colSpan={7} align="center">No machine usage found.</TableCell></TableRow>}
        </TableBody>
      </Table></TableContainer>
    </Card>

    <Card sx={{ overflow: 'hidden' }}>
      <Box sx={{ px: 2, py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Typography fontWeight={800}>Job-wise Click History</Typography>
        <Typography color="text.secondary" fontSize={12}>Every click contribution is calculated from the In Job, so edits and machine changes are reflected without duplicate entries.</Typography>
      </Box>
      <TableContainer><Table size="small" sx={{ minWidth: 850 }}>
        <TableHead><TableRow><TableCell>Job</TableCell><TableCell>Job name</TableCell><TableCell>Machine</TableCell><TableCell>Printing operator</TableCell><TableCell align="right">Clicks</TableCell><TableCell>Last updated</TableCell></TableRow></TableHead>
        <TableBody>{machines.flatMap((machine) => machine.jobs).map((job) => <TableRow key={job.id} hover>
          <TableCell>{job.job_number}</TableCell><TableCell>{job.job_name || '—'}</TableCell><TableCell>{job.machine_name}</TableCell><TableCell>{job.printing_operator || '—'}</TableCell><TableCell align="right" sx={{ fontWeight: 800 }}>{number(job.click_count)}</TableCell><TableCell>{dateTimeLabel(job.updated_at)}</TableCell>
        </TableRow>)}
          {!daily.isLoading && machines.every((machine) => machine.jobs.length === 0) && <TableRow><TableCell colSpan={6} align="center">No In-Job click entries for this date.</TableCell></TableRow>}
        </TableBody>
      </Table></TableContainer>
    </Card>

    <Card sx={{ overflow: 'hidden' }}>
      <Box sx={{ px: 2, py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Typography fontWeight={800}>Today's Machine Count — Morning &amp; Ending</Typography>
        <Typography color="text.secondary" fontSize={12}>Enter the opening count at the start of the shift and the closing count at the end. Each machine has one counter record per date; you can correct that date's readings here.</Typography>
      </Box>
      {error && <Alert severity="error" sx={{ m: 1.5 }}>{error}</Alert>}
      <TableContainer><Table size="small" sx={{ minWidth: 730 }}>
        <TableHead><TableRow><TableCell>Machine</TableCell><TableCell>Morning count · {dateLabel(date)}</TableCell><TableCell>Ending count · {dateLabel(date)}</TableCell><TableCell align="right">Actual clicks</TableCell><TableCell /></TableRow></TableHead>
        <TableBody>{machines.map((row) => {
          const values = rowDraft(row)
          const actual = values.morning !== '' && values.ending !== '' && Number(values.ending) >= Number(values.morning)
            ? Number(values.ending) - Number(values.morning) : null
          return <TableRow key={row.machine_id}>
            <TableCell sx={{ fontWeight: 700 }}>{row.machine_name}</TableCell>
            <TableCell><TextField size="small" type="number" placeholder="Enter count" value={values.morning} onChange={(event) => updateDraft(row, 'morning', event.target.value)} inputProps={{ min: 0, step: 1 }} /></TableCell>
            <TableCell><TextField size="small" type="number" placeholder="Enter count" value={values.ending} onChange={(event) => updateDraft(row, 'ending', event.target.value)} inputProps={{ min: Number(values.morning || 0), step: 1 }} /></TableCell>
            <TableCell align="right">{number(actual)}</TableCell>
            <TableCell align="right"><Button size="small" variant="contained" onClick={() => save.mutate({ row, values })} disabled={!saveable(row) || save.isPending}>{row.counter_id ? 'Update' : 'Save'}</Button></TableCell>
          </TableRow>
        })}
          {!daily.isLoading && machines.length === 0 && <TableRow><TableCell colSpan={5} align="center">No active machines found.</TableCell></TableRow>}
        </TableBody>
      </Table></TableContainer>
    </Card>

    <Card sx={{ overflow: 'hidden' }}>
      <Box sx={{ px: 2, py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}><Typography fontWeight={800}>Recent Counters — All Machines</Typography></Box>
      {history.isError && <Alert severity="error" sx={{ m: 1.5 }}>{apiError(history.error)}</Alert>}
      {history.isLoading ? <Box sx={{ py: 3, textAlign: 'center' }}><CircularProgress size={22} /></Box> : <TableContainer><Table size="small" sx={{ minWidth: 850 }}>
        <TableHead><TableRow><TableCell>Date</TableCell><TableCell>Machine</TableCell><TableCell>Operator</TableCell><TableCell align="right">Morning</TableCell><TableCell align="right">Ending</TableCell><TableCell align="right">Actual clicks</TableCell><TableCell align="right">Overall clicks</TableCell></TableRow></TableHead>
        <TableBody>{recent.map((row) => <TableRow key={row.id} hover><TableCell>{dateLabel(row.count_date)}</TableCell><TableCell>{row.machine_name}</TableCell><TableCell>{row.operator_display || '—'}</TableCell><TableCell align="right">{number(row.morning_count)}</TableCell><TableCell align="right">{number(row.ending_count)}</TableCell><TableCell align="right">{number(row.actual_clicks)}</TableCell><TableCell align="right">{number(row.job_clicks_booked)}</TableCell></TableRow>)}
          {recent.length === 0 && <TableRow><TableCell colSpan={7} align="center">No machine counters recorded yet.</TableCell></TableRow>}
        </TableBody>
      </Table></TableContainer>}
    </Card>
  </Stack>
}
