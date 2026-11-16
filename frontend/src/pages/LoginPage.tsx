import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { Alert, Box, Button, Checkbox, FormControlLabel, TextField, Typography } from '@mui/material'
import ArrowForwardRounded from '@mui/icons-material/ArrowForwardRounded'
import AutoAwesomeRounded from '@mui/icons-material/AutoAwesomeRounded'
import { useAuth } from '../auth/AuthContext'
import { apiError } from '../api/client'

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const { auth, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  if (auth) return <Navigate to="/" replace />

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setPending(true); setError('')
    try {
      await login(username, password)
      const target = (location.state as { from?: string } | null)?.from || '/'
      navigate(target, { replace: true })
    } catch (loginError) {
      setError(apiError(loginError))
    } finally {
      setPending(false)
    }
  }

  return (
    <Box className="login-shell">
      <Box className="login-visual">
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, position: 'relative', zIndex: 1 }}>
          <Box className="brand-mark">SP</Box>
          <Box><Typography fontFamily="DM Sans" fontSize={19} fontWeight={800}>Shiva Prints</Typography><Typography fontSize={11} color="rgba(255,255,255,.55)" letterSpacing=".12em">WORKFLOW OS</Typography></Box>
        </Box>
        <Box sx={{ maxWidth: 640, position: 'relative', zIndex: 1 }}>
          <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 1, px: 1.5, py: .7, border: '1px solid rgba(255,255,255,.15)', borderRadius: 10, mb: 3 }}><AutoAwesomeRounded sx={{ fontSize: 16, color: '#ff986f' }} /><Typography fontSize={12} fontWeight={700}>One workspace. Every print job.</Typography></Box>
          <Typography variant="h1" sx={{ fontSize: { xs: 42, lg: 64 }, lineHeight: 1.02, letterSpacing: '-.05em', mb: 2.5 }}>From first brief<br />to final delivery.</Typography>
          <Typography color="rgba(255,255,255,.62)" fontSize={{ xs: 15, lg: 17 }} lineHeight={1.7}>Manage your pipeline, production floor, vendors, stock, payments, and delivery without losing the thread.</Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 5, position: 'relative', zIndex: 1 }}>
          {[['Pipeline', 'Clear handoffs'], ['Production', 'Live status'], ['Finance', 'Balanced ledgers']].map(([title, subtitle]) => <Box key={title}><Typography fontWeight={750}>{title}</Typography><Typography fontSize={12} color="rgba(255,255,255,.48)">{subtitle}</Typography></Box>)}
        </Box>
      </Box>
      <Box className="login-panel">
        <Box className="login-card" component="form" onSubmit={submit}>
          <Typography variant="h4" sx={{ fontSize: 32, letterSpacing: '-.04em' }}>Welcome back</Typography>
          <Typography color="text.secondary" sx={{ mt: 1, mb: 4 }}>Sign in to continue to the print operations dashboard.</Typography>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          <TextField fullWidth label="Username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required sx={{ mb: 2 }} />
          <TextField fullWidth label="Password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          <FormControlLabel control={<Checkbox size="small" defaultChecked />} label={<Typography fontSize={13}>Keep me signed in on this device</Typography>} sx={{ my: 1.5 }} />
          <Button fullWidth variant="contained" size="large" type="submit" disabled={pending} endIcon={<ArrowForwardRounded />}>{pending ? 'Signing in…' : 'Sign in'}</Button>
          <Typography fontSize={12} color="text.secondary" textAlign="center" sx={{ mt: 3 }}>Access is controlled by your assigned role and module permissions.</Typography>
        </Box>
      </Box>
    </Box>
  )
}
