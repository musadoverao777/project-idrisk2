interface LoadingOverlayProps {
  message?: string
}

export function LoadingOverlay({
  message = 'A classificar imagem… Isto pode demorar até 2 minutos.',
}: LoadingOverlayProps) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-4 rounded-xl border border-slate-200 bg-slate-50 p-12 text-center"
      role="status"
      aria-live="polite"
    >
      <div
        className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-emerald-600"
        aria-hidden="true"
      />
      <p className="max-w-sm text-sm text-slate-600">{message}</p>
    </div>
  )
}
