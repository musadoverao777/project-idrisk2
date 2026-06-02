export type ConfidenceLevel = 'high' | 'medium' | 'low'

export interface ClassificationResult {
  base_term_code: string
  base_term_label: string
  facets: Record<string, string>
  reasoning: string
  confidence: ConfidenceLevel
  requires_human_review: boolean
  classification_id: string
  timestamp: string
  total_time_ms: number
  ocr_text: string
  retrieved_sources: string[]
}

export interface HealthStatus {
  status: string
  pipeline_ready: boolean
  message: string
}
