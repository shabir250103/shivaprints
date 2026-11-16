import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import {
  AppBar, Avatar, Badge, Box, Divider, Drawer, IconButton, List, ListItemButton,
  ListItemIcon, ListItemText, Menu, MenuItem, Toolbar, Tooltip, Typography,
} from '@mui/material'
import DashboardRounded from '@mui/icons-material/DashboardRounded'
import ViewKanbanRounded from '@mui/icons-material/ViewKanbanRounded'
import AssignmentTurnedInRounded from '@mui/icons-material/AssignmentTurnedInRounded'
import FactoryRounded from '@mui/icons-material/FactoryRounded'
import LocalShippingRounded from '@mui/icons-material/LocalShippingRounded'
import Inventory2Rounded from '@mui/icons-material/Inventory2Rounded'
import GroupsRounded from '@mui/icons-material/GroupsRounded'
import PrecisionManufacturingRounded from '@mui/icons-material/PrecisionManufacturingRounded'
import DeleteSweepRounded from '@mui/icons-material/DeleteSweepRounded'
import ReceiptLongRounded from '@mui/icons-material/ReceiptLongRounded'
import AssessmentRounded from '@mui/icons-material/AssessmentRounded'
import NotificationsRounded from '@mui/icons-material/NotificationsRounded'
import MenuRounded from '@mui/icons-material/MenuRounded'
import SearchRounded from '@mui/icons-material/SearchRounded'
import LogoutRounded from '@mui/icons-material/LogoutRounded'
import FollowTheSignsRounded from '@mui/icons-material/FollowTheSignsRounded'
import AccountBalanceWalletRounded from '@mui/icons-material/AccountBalanceWalletRounded'
import PaymentsRounded from '@mui/icons-material/PaymentsRounded'
import BusinessRounded from '@mui/icons-material/BusinessRounded'
import { useAuth } from '../auth/AuthContext'
import { api } from '../api/client'
import { brandingLogoUrl, useBranding } from '../branding/BrandingContext'

const drawerWidth = 256

const nav = [
  { label: 'Dashboard', path: '/', permission: 'dashboard', icon: DashboardRounded },
  { label: 'Enquiries', path: '/enquiries', permission: 'followups', icon: FollowTheSignsRounded },
  { label: 'Quotations', path: '/quotations', permission: 'quotations', icon: PaymentsRounded },
  { label: 'Pipeline', path: '/pipeline', permission: 'pipeline', icon: ViewKanbanRounded },
  { label: 'In Jobs', path: '/in-jobs', permission: 'injobs', icon: FactoryRounded },
  { label: 'Out Jobs', path: '/out-jobs', permission: 'outjobs', icon: LocalShippingRounded },
  { label: 'Job Board', path: '/job-board', permission: 'jobboard', icon: AssignmentTurnedInRounded },
  { label: 'Deliveries', path: '/deliveries', permission: 'delivery', icon: LocalShippingRounded },
  { label: 'Invoices', path: '/invoices', permission: 'accounts', icon: ReceiptLongRounded },
  { label: 'Finance', path: '/finance', permission: 'finance', icon: AccountBalanceWalletRounded },
  { label: 'Customers', path: '/customers', permission: 'customers', icon: GroupsRounded },
  { label: 'Suppliers', path: '/suppliers', permission: 'suppliers', icon: GroupsRounded },
  { label: 'Stock', path: '/stock', permission: 'stock', icon: Inventory2Rounded },
  { label: 'Machines', path: '/machines', permission: 'machine', icon: PrecisionManufacturingRounded },
  { label: 'Wastage', path: '/wastage', permission: 'wastage', icon: DeleteSweepRounded },
  { label: 'Reports', path: '/reports', permission: 'reports', icon: AssessmentRounded },
  { label: 'Company Settings', path: '/company-settings', permission: 'company_settings', icon: BusinessRounded },
  { label: 'Team & Access', path: '/team-access', permission: 'teamaccess', icon: GroupsRounded },
  { label: 'Branches', path: '/branches', permission: 'users', icon: BusinessRounded },
]

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null)
  const { auth, logout, can, canShowPayments } = useAuth()
  const branding = useBranding()
  const notificationsEnabled = can('notifications')
  const unreadNotifications = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: async () => (await api.get<Array<{ id: number }>>('/notifications/', { params: { read: false } })).data,
    enabled: notificationsEnabled,
    refetchInterval: 30_000,
  })
  const location = useLocation()
  const navigate = useNavigate()
  const visibleNav = useMemo(() => nav.filter((item) => {
    if (!canShowPayments && ['finance', 'cash', 'accounts'].includes(item.permission)) {
      return false
    }
    if (item.permission === 'jobboard') {
      return can('jobboard') && (can('injobs') || can('outjobs'))
    }
    if (item.permission === 'teamaccess') {
      return can('users') || can('permissions')
    }
    if (item.path === '/invoices') {
      return can('accounts') || can('delivery')
    }
    return can(item.permission)
  }), [auth, canShowPayments, can])
  const userName = [auth?.user.first_name, auth?.user.last_name].filter(Boolean).join(' ') || auth?.user.username || 'User'
  const initials = userName.split(' ').map((part) => part[0]).join('').slice(0, 2).toUpperCase()
  const unreadCount = unreadNotifications.data?.length || 0

  const drawer = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: '#17212b', color: 'white' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.4, px: 2.5, minHeight: 78 }}>
        {brandingLogoUrl(branding.company_logo_url) ? <Box component="img" src={brandingLogoUrl(branding.company_logo_url)} alt="Company logo" sx={{ width: 34, height: 34, objectFit: 'contain', borderRadius: 1 }} /> : <Box className="brand-mark">SP</Box>}
        <Box>
          <Typography fontFamily="DM Sans" fontWeight={800} fontSize={17}>{branding.company_name}</Typography>
          <Typography fontSize={11} color="rgba(255,255,255,.52)" letterSpacing=".08em">WORKFLOW OS</Typography>
        </Box>
      </Box>
      <Divider sx={{ borderColor: 'rgba(255,255,255,.08)' }} />
      <List sx={{ px: 1.4, py: 2, overflow: 'auto', flex: 1 }}>
        {visibleNav.map(({ label, path, icon: Icon }) => (
          <ListItemButton
            key={path}
            component={NavLink}
            to={path}
            end={path === '/'}
            onClick={() => setMobileOpen(false)}
            sx={{
              borderRadius: 2.2, mb: .45, minHeight: 44, color: 'rgba(255,255,255,.68)',
              '& .MuiListItemIcon-root': { color: 'inherit' },
              '&.active': { color: 'white', bgcolor: 'rgba(239,108,62,.19)', '&::before': { content: '""', width: 3, height: 22, bgcolor: 'primary.main', borderRadius: 2, mr: 1.5 } },
              '&:hover': { bgcolor: 'rgba(255,255,255,.07)', color: 'white' },
            }}
          >
            <ListItemIcon sx={{ minWidth: 37 }}><Icon fontSize="small" /></ListItemIcon>
            <ListItemText primary={label} slotProps={{ primary: { fontSize: 13.5, fontWeight: 650 } }} />
          </ListItemButton>
        ))}
      </List>
      <Box sx={{ m: 1.5, p: 1.5, borderRadius: 2.5, bgcolor: 'rgba(255,255,255,.055)' }}>
        <Typography fontSize={11} color="rgba(255,255,255,.45)" textTransform="uppercase">Signed in as</Typography>
        <Typography fontSize={13.5} fontWeight={700} noWrap>{userName}</Typography>
        <Typography fontSize={12} color="rgba(255,255,255,.5)" noWrap>{auth?.user.role_name || (auth?.user.is_superuser ? 'Super administrator' : 'Team member')}</Typography>
      </Box>
    </Box>
  )

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar position="fixed" elevation={0} sx={{ ml: { md: `${drawerWidth}px` }, width: { md: `calc(100% - ${drawerWidth}px)` }, bgcolor: 'rgba(245,243,239,.9)', backdropFilter: 'blur(12px)', color: 'text.primary', borderBottom: '1px solid', borderColor: 'divider' }}>
        <Toolbar sx={{ minHeight: '70px !important', px: { xs: 2, md: 3.5 } }}>
          <IconButton onClick={() => setMobileOpen(true)} sx={{ display: { md: 'none' }, mr: 1 }}><MenuRounded /></IconButton>
          <Box sx={{ flex: 1, display: 'flex', alignItems: 'center' }}>
            <SearchRounded sx={{ display: { xs: 'none', sm: 'block' }, color: 'text.disabled', mr: 1 }} />
            <Typography sx={{ display: { xs: 'none', sm: 'block' }, color: 'text.secondary', fontSize: 13 }}>Search is available inside every module</Typography>
          </Box>
          {notificationsEnabled && <Tooltip title={unreadCount ? `${unreadCount} unread notifications` : 'Notifications'}>
            <IconButton onClick={() => navigate('/notifications')} color={location.pathname === '/notifications' ? 'primary' : 'default'} aria-label={unreadCount ? `${unreadCount} unread notifications` : 'Notifications'}>
              <Badge badgeContent={unreadCount} color="primary" max={99}><NotificationsRounded /></Badge>
            </IconButton>
          </Tooltip>}
          <IconButton onClick={(event) => setMenuAnchor(event.currentTarget)} sx={{ ml: 1 }}>
            <Avatar sx={{ width: 36, height: 36, bgcolor: 'secondary.main', fontSize: 13, fontWeight: 800 }}>{initials}</Avatar>
          </IconButton>
          <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={() => setMenuAnchor(null)}>
            {can('company_settings') && <MenuItem onClick={() => { setMenuAnchor(null); navigate('/company-settings') }}><BusinessRounded fontSize="small" sx={{ mr: 1.5 }} /> Company Settings</MenuItem>}
            {notificationsEnabled && <MenuItem onClick={() => { setMenuAnchor(null); navigate('/notifications') }}><NotificationsRounded fontSize="small" sx={{ mr: 1.5 }} /> Notifications</MenuItem>}
            <MenuItem onClick={logout}><LogoutRounded fontSize="small" sx={{ mr: 1.5 }} /> Sign out</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Box component="nav" sx={{ width: { md: drawerWidth }, flexShrink: { md: 0 } }}>
        <Drawer variant="temporary" open={mobileOpen} onClose={() => setMobileOpen(false)} ModalProps={{ keepMounted: true }} sx={{ display: { xs: 'block', md: 'none' }, '& .MuiDrawer-paper': { width: drawerWidth } }}>{drawer}</Drawer>
        <Drawer variant="permanent" open sx={{ display: { xs: 'none', md: 'block' }, '& .MuiDrawer-paper': { width: drawerWidth, border: 0 } }}>{drawer}</Drawer>
      </Box>
      <Box component="main" sx={{ flex: 1, minWidth: 0, pt: '70px' }}>
        <Box className="fade-up" sx={{ p: { xs: 2, sm: 3, lg: 4 }, maxWidth: 1540, mx: 'auto' }}><Outlet /></Box>
      </Box>
    </Box>
  )
}
