import { createContext, useContext, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, resolveMediaUrl } from '../api/client'

export interface Branding { company_name: string; company_logo_url?: string }
const fallback: Branding = { company_name: 'Shiva Prints' }
const BrandingContext = createContext<Branding>(fallback)

export function BrandingProvider({ children }: { children: React.ReactNode }) {
  const query = useQuery({
    queryKey: ['company-settings', 'branding'],
    queryFn: async () => (await api.get<Branding>('/company-settings/public-branding/')).data,
  })
  const branding = query.data?.company_name ? query.data : fallback
  useEffect(() => { document.title = branding.company_name || fallback.company_name }, [branding.company_name])
  return <BrandingContext.Provider value={branding}>{children}</BrandingContext.Provider>
}

export function useBranding() { return useContext(BrandingContext) }
export function brandingLogoUrl(url?: string) { return url ? resolveMediaUrl(url) : '' }
