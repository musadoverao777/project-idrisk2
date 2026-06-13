import type {
  ClassificationResult,
  HealthStatus,
  HistoryItem,
  ReviewItem,
  UserItem,
  AuditItem,
  DashboardStats,
} from '../types/classification'

const CLASSIFY_TIMEOUT_MS = 180_000

// Endereço base do backend.
// Prioridade: ?api=<url> (guardado em localStorage) > VITE_API_BASE (build) > '' (relativo, dev local com proxy Vite).
// Permite apontar o frontend publicado (Vercel) para um backend remoto (túnel/HF Spaces)
// sem republicar: basta abrir o link com ?api=https://meu-backend.exemplo uma vez.
function resolveApiBase(): string {
  let base = (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE ?? ''
  try {
    const params = new URLSearchParams(window.location.search)
    const fromQuery = params.get('api')
    if (fromQuery !== null) {
      if (fromQuery === '') {
        window.localStorage.removeItem('idrisk2_api_base')
      } else {
        window.localStorage.setItem('idrisk2_api_base', fromQuery)
      }
    }
    const stored = window.localStorage.getItem('idrisk2_api_base')
    if (stored) base = stored
  } catch {
    // localStorage indisponível — usa o valor de build
  }
  return base.replace(/\/$/, '')
}

const API_BASE = resolveApiBase()

async function parseError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: string | { msg: string }[] }
    if (typeof data.detail === 'string') return data.detail
    if (Array.isArray(data.detail)) {
      return data.detail.map((item) => item.msg).join('; ')
    }
  } catch {
    // ignore JSON parse errors
  }
  return `Erro HTTP ${response.status}`
}

export async function checkHealth(): Promise<HealthStatus> {
  const response = await fetch(`${API_BASE}/api/health`)
  if (!response.ok) {
    throw new Error(`API indisponível (${response.status})`)
  }
  return response.json() as Promise<HealthStatus>
}

export async function getHistory(limit = 500): Promise<HistoryItem[]> {
  const response = await fetch(`${API_BASE}/api/history?limit=${limit}`)
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  return response.json() as Promise<HistoryItem[]>
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) throw new Error(await parseError(response))
  return response.json() as Promise<T>
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await parseError(response))
  return response.json() as Promise<T>
}

// --- Revisão humana ---
export function getReviews(status: string | null = 'pending'): Promise<ReviewItem[]> {
  const q = status ? `?status=${status}` : '?status='
  return getJson<ReviewItem[]>(`/api/reviews${q}`)
}

export function decideReview(
  classificationId: string,
  decision: { status: 'approved' | 'rejected'; corrected_code?: string; notes?: string; reviewer_id?: string },
): Promise<ReviewItem> {
  return postJson<ReviewItem>(`/api/reviews/${classificationId}/decision`, decision)
}

// --- Utilizadores ---
export function getUsers(): Promise<UserItem[]> {
  return getJson<UserItem[]>('/api/users')
}

export function createUser(payload: { username: string; email: string; role: string }): Promise<UserItem> {
  return postJson<UserItem>('/api/users', payload)
}

export function setUserStatus(userId: string, status: 'active' | 'inactive'): Promise<{ id: string; status: string }> {
  return postJson<{ id: string; status: string }>(`/api/users/${userId}/status`, { status })
}

// --- Auditoria ---
export function getAudit(limit = 500): Promise<AuditItem[]> {
  return getJson<AuditItem[]>(`/api/audit?limit=${limit}`)
}

// --- Estatísticas ---
export function getStats(): Promise<DashboardStats> {
  return getJson<DashboardStats>('/api/stats')
}

export async function classifyImage(file: File): Promise<ClassificationResult> {
  const formData = new FormData()
  formData.append('file', file)

  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), CLASSIFY_TIMEOUT_MS)

  try {
    const response = await fetch(`${API_BASE}/api/classify`, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    })

    if (!response.ok) {
      throw new Error(await parseError(response))
    }

    return response.json() as Promise<ClassificationResult>
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Tempo limite excedido. A classificação pode demorar até 2 minutos.')
    }
    throw error
  } finally {
    window.clearTimeout(timeoutId)
  }
}
