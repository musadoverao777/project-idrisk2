export type ConfidenceLevel = 'high' | 'medium' | 'low'

export interface FacetReadable {
  group: string
  group_label: string
  code: string
  label: string | null
}

export interface ClassificationResult {
  base_term_code: string
  base_term_label: string
  facets: Record<string, string>
  facets_readable: FacetReadable[]
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

export type ReviewStatus = 'none' | 'pending' | 'approved' | 'rejected'

export interface HistoryItem {
  id: string
  timestamp: string
  base_term_code: string
  base_term_label: string
  facets: Record<string, string>
  confidence: ConfidenceLevel
  requires_human_review: boolean
  review_status: ReviewStatus
  ocr_text: string
  image_hash: string | null
  submitted_by: string | null
  total_time_ms: number | null
}

export interface ReviewItem {
  classification_id: string
  status: ReviewStatus
  created_at: string | null
  reviewer_id: string | null
  corrected_code: string | null
  notes: string | null
  reviewed_at: string | null
  submitted_by: string | null
  timestamp: string
  base_term_code: string
  base_term_label: string
  confidence: ConfidenceLevel
  ocr_text: string
}

export interface UserItem {
  id: string
  username: string
  email: string | null
  role: 'inspector' | 'supervisor' | 'administrator' | 'auditor'
  status: 'active' | 'inactive'
  created_at: string | null
}

export interface AuditItem {
  entry_id: string
  timestamp: string
  event_type: string | null
  user_id: string | null
  details: Record<string, unknown>
  previous_hmac: string | null
  hmac: string | null
}

export interface WeeklyPoint {
  day: string
  date: string
  classifications: number
}

export interface DashboardStats {
  confidence: { high: number; medium: number; low: number }
  weekly: WeeklyPoint[]
  total: number
  pending_reviews: number
}
