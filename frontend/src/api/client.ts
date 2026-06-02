import type { ClassificationResult, HealthStatus } from '../types/classification'

const CLASSIFY_TIMEOUT_MS = 180_000

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
  const response = await fetch('/api/health')
  if (!response.ok) {
    throw new Error(`API indisponível (${response.status})`)
  }
  return response.json() as Promise<HealthStatus>
}

export async function classifyImage(file: File): Promise<ClassificationResult> {
  const formData = new FormData()
  formData.append('file', file)

  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), CLASSIFY_TIMEOUT_MS)

  try {
    const response = await fetch('/api/classify', {
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
