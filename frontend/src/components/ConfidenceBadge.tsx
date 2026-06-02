import type { ConfidenceLevel } from '../types/classification'

const STYLES: Record<ConfidenceLevel, string> = {
  high: 'bg-emerald-100 text-emerald-800 ring-emerald-200',
  medium: 'bg-amber-100 text-amber-800 ring-amber-200',
  low: 'bg-red-100 text-red-800 ring-red-200',
}

const LABELS: Record<ConfidenceLevel, string> = {
  high: 'Alta',
  medium: 'Média',
  low: 'Baixa',
}

interface ConfidenceBadgeProps {
  confidence: ConfidenceLevel
}

export function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-medium ring-1 ring-inset ${STYLES[confidence]}`}
    >
      Confiança: {LABELS[confidence]}
    </span>
  )
}
