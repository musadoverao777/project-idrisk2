import { useCallback, useEffect, useState } from 'react'
import { checkHealth, classifyImage } from './api/client'
import { ClassificationResult } from './components/ClassificationResult'
import { ImageUpload } from './components/ImageUpload'
import { LoadingOverlay } from './components/LoadingOverlay'
import type { ClassificationResult as Result, HealthStatus } from './types/classification'

type AppState = 'idle' | 'loading' | 'success' | 'error'

function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState<AppState>('idle')
  const [health, setHealth] = useState<HealthStatus | null>(null)

  useEffect(() => {
    checkHealth()
      .then(setHealth)
      .catch(() =>
        setHealth({
          status: 'error',
          pipeline_ready: false,
          message: 'Não foi possível contactar a API',
        }),
      )
  }, [])

  const handleClassify = useCallback(async () => {
    if (!selectedFile) return

    setState('loading')
    setError(null)
    setResult(null)

    try {
      const classification = await classifyImage(selectedFile)
      setResult(classification)
      setState('success')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro desconhecido')
      setState('error')
    }
  }, [selectedFile])

  const pipelineReady = health?.pipeline_ready ?? false

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
          <h1 className="text-2xl font-bold text-slate-900">IDRISK2</h1>
          <p className="mt-1 text-sm text-slate-600">
            Classificação automática de produtos alimentares na taxonomia EFSA FoodEx2
          </p>
          {health && (
            <p
              className={`mt-2 text-xs ${pipelineReady ? 'text-emerald-700' : 'text-amber-700'}`}
              role="status"
            >
              {pipelineReady ? '● Pipeline pronto' : `● ${health.message}`}
            </p>
          )}
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 px-4 py-8 sm:px-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-slate-800">Enviar imagem</h2>
          <ImageUpload
            selectedFile={selectedFile}
            onFileSelect={setSelectedFile}
            disabled={state === 'loading'}
          />
          <button
            type="button"
            onClick={() => void handleClassify()}
            disabled={!selectedFile || state === 'loading' || !pipelineReady}
            className="mt-6 w-full rounded-lg bg-emerald-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {state === 'loading' ? 'A classificar…' : 'Classificar'}
          </button>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-slate-800">Resultado</h2>

          {state === 'idle' && (
            <div className="flex min-h-64 items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center">
              <p className="text-sm text-slate-500">
                Envie uma imagem de rótulo ou prato preparado para obter a classificação FoodEx2.
              </p>
            </div>
          )}

          {state === 'loading' && <LoadingOverlay />}

          {state === 'error' && error && (
            <div
              className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
              role="alert"
            >
              {error}
            </div>
          )}

          {state === 'success' && result && <ClassificationResult result={result} />}
        </section>
      </main>
    </div>
  )
}

export default App
