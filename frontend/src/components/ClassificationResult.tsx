import { useState } from 'react'
import type { ClassificationResult as Result } from '../types/classification'
import { ConfidenceBadge } from './ConfidenceBadge'

interface ClassificationResultProps {
  result: Result
}

export function ClassificationResult({ result }: ClassificationResultProps) {
  const [showReasoning, setShowReasoning] = useState(false)
  const facetEntries = Object.entries(result.facets)

  return (
    <div className="flex flex-col gap-5 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Classificação FoodEx2
          </p>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">{result.base_term_label}</h2>
          <p className="mt-1 font-mono text-sm text-emerald-700">{result.base_term_code}</p>
        </div>
        <ConfidenceBadge confidence={result.confidence} />
      </div>

      {result.requires_human_review && (
        <div
          className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="alert"
        >
          Esta classificação requer revisão humana antes de uso regulatório.
        </div>
      )}

      {facetEntries.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-700">Facetas</h3>
          <dl className="grid gap-2 sm:grid-cols-2">
            {facetEntries.map(([key, value]) => (
              <div key={key} className="rounded-md bg-slate-50 px-3 py-2">
                <dt className="font-mono text-xs text-slate-500">{key}</dt>
                <dd className="text-sm font-medium text-slate-800">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div>
        <button
          type="button"
          onClick={() => setShowReasoning((prev) => !prev)}
          className="text-sm font-medium text-emerald-700 hover:text-emerald-800 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2"
          aria-expanded={showReasoning}
        >
          {showReasoning ? 'Ocultar raciocínio' : 'Ver raciocínio'}
        </button>
        {showReasoning && (
          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
            {result.reasoning}
          </p>
        )}
      </div>

      {result.ocr_text && (
        <div>
          <h3 className="mb-1 text-sm font-semibold text-slate-700">Texto OCR</h3>
          <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-600">{result.ocr_text}</p>
        </div>
      )}

      {result.retrieved_sources.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold text-slate-700">Fontes EFSA</h3>
          <ul className="list-inside list-disc text-sm text-slate-600">
            {result.retrieved_sources.map((source) => (
              <li key={source}>{source}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="border-t border-slate-100 pt-4 text-xs text-slate-500">
        <p>ID: {result.classification_id}</p>
        <p>Processado em {(result.total_time_ms / 1000).toFixed(1)} s</p>
        <p>{new Date(result.timestamp).toLocaleString('pt-PT')}</p>
      </div>
    </div>
  )
}
