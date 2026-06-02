import { useCallback, useRef, useState } from 'react'

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif']
const ACCEPTED_EXTENSIONS = '.jpg,.jpeg,.png,.webp,.heic,.heif'

interface ImageUploadProps {
  onFileSelect: (file: File) => void
  disabled?: boolean
  selectedFile: File | null
}

export function ImageUpload({ onFileSelect, disabled = false, selectedFile }: ImageUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const validateAndSelect = useCallback(
    (file: File | undefined) => {
      if (!file) return

      if (!ACCEPTED_TYPES.includes(file.type) && !file.name.match(/\.(jpe?g|png|webp|heic|heif)$/i)) {
        setError('Formato não suportado. Use JPG, PNG, WEBP ou HEIC.')
        return
      }

      if (file.size > 20 * 1024 * 1024) {
        setError('Ficheiro demasiado grande (máx. 20 MB).')
        return
      }

      setError(null)
      setPreviewUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev)
        return URL.createObjectURL(file)
      })
      onFileSelect(file)
    },
    [onFileSelect],
  )

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault()
      setIsDragging(false)
      if (disabled) return
      validateAndSelect(event.dataTransfer.files[0])
    },
    [disabled, validateAndSelect],
  )

  const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    if (!disabled) setIsDragging(true)
  }

  const handleDragLeave = () => setIsDragging(false)

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    validateAndSelect(event.target.files?.[0])
  }

  const displayPreview = previewUrl && selectedFile

  return (
    <div className="flex flex-col gap-4">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(event) => {
          if ((event.key === 'Enter' || event.key === ' ') && !disabled) {
            event.preventDefault()
            inputRef.current?.click()
          }
        }}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label="Área de upload de imagem"
        className={[
          'flex min-h-64 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 transition-colors',
          isDragging
            ? 'border-emerald-500 bg-emerald-50'
            : 'border-slate-300 bg-white hover:border-emerald-400 hover:bg-slate-50',
          disabled ? 'pointer-events-none opacity-60' : '',
        ].join(' ')}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS}
          className="hidden"
          onChange={handleInputChange}
          disabled={disabled}
          aria-hidden="true"
        />

        {displayPreview ? (
          <img
            src={previewUrl}
            alt={`Pré-visualização de ${selectedFile.name}`}
            className="max-h-48 max-w-full rounded-lg object-contain"
          />
        ) : (
          <>
            <svg
              className="mb-3 h-12 w-12 text-slate-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
              />
            </svg>
            <p className="text-sm font-medium text-slate-700">
              Arraste uma imagem ou clique para selecionar
            </p>
            <p className="mt-1 text-xs text-slate-500">JPG, PNG, WEBP ou HEIC — máx. 20 MB</p>
          </>
        )}
      </div>

      {selectedFile && (
        <p className="truncate text-sm text-slate-600" title={selectedFile.name}>
          Ficheiro: <span className="font-medium">{selectedFile.name}</span>
        </p>
      )}

      {error && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
