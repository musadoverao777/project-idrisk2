import { useState, useCallback, useEffect, useRef } from 'react';
import { Upload, AlertCircle, CheckCircle2, XCircle, ArrowLeft } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Progress } from './ui/progress';
import { Button } from './ui/button';
import { classifyImage } from '../../api/client';
import type { ClassificationResult } from '../../types/classification';

// Pipeline stages shown in sequence while the backend processes the image.
const STAGES = [
  { label: 'Uploading image...', duration: 1500 },
  { label: 'Running OCR extraction...', duration: 3000 },
  { label: 'Processing with Vision-Language Model...', duration: 8000 },
  { label: 'Performing RAG retrieval...', duration: 5000 },
  { label: 'Classifying to FoodEx2 taxonomy...', duration: 4000 },
];

const CONFIDENCE_STYLES: Record<string, string> = {
  high:   'bg-green-100 text-green-800 border-green-300',
  medium: 'bg-amber-100 text-amber-800 border-amber-300',
  low:    'bg-red-100 text-red-800 border-red-300',
};

export function InspectorSubmission() {
  const [file, setFile]             = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [progress, setProgress]     = useState(0);
  const [stageLabel, setStageLabel] = useState('');
  const [result, setResult]         = useState<ClassificationResult | null>(null);
  const [error, setError]           = useState<string | null>(null);

  const animFrameRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelAnimation = () => {
    if (animFrameRef.current) clearTimeout(animFrameRef.current);
  };

  const runProgressAnimation = useCallback(() => {
    let stageIdx = 0;
    let elapsed  = 0;
    const total  = STAGES.reduce((s, st) => s + st.duration, 0);
    const tick = () => {
      if (stageIdx >= STAGES.length) return;
      const stage = STAGES[stageIdx];
      setStageLabel(stage.label);
      elapsed += stage.duration;
      setProgress(Math.min(95, Math.round((elapsed / total) * 100)));
      stageIdx++;
      if (stageIdx < STAGES.length) {
        animFrameRef.current = setTimeout(tick, stage.duration);
      }
    };
    tick();
  }, []);

  const processImage = useCallback(async (imageFile: File) => {
    setProcessing(true);
    setProgress(0);
    setResult(null);
    setError(null);
    runProgressAnimation();
    try {
      const data = await classifyImage(imageFile);
      cancelAnimation();
      setProgress(100);
      setStageLabel('Classification complete');
      setResult(data);
    } catch (err) {
      cancelAnimation();
      setError(err instanceof Error ? err.message : 'Unexpected error. Is the backend running?');
    } finally {
      setProcessing(false);
    }
  }, [runProgressAnimation]);

  useEffect(() => () => cancelAnimation(), []);
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const selectFile = (selected: File) => {
    setFile(selected);
    setPreviewUrl(URL.createObjectURL(selected));
    processImage(selected);
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped && dropped.type.startsWith('image/')) selectFile(dropped);
  }, [processImage]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) selectFile(selected);
  };

  const handleReset = () => {
    setFile(null);
    setPreviewUrl(null);
    setResult(null);
    setError(null);
    setProgress(0);
    setStageLabel('');
  };

  const showResultPage = !!result && !processing;

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900 mb-1">
            {showResultPage ? 'Classification Result' : 'Image Submission'}
          </h2>
          <p className="text-sm text-slate-600">
            {showResultPage
              ? 'FoodEx2 taxonomy mapping and confidence assessment'
              : 'Upload food label images for FoodEx2 classification'}
          </p>
        </div>
        {(result || error) && (
          <Button variant="outline" onClick={handleReset}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            New Classification
          </Button>
        )}
      </div>

      {/* ── Idle: upload ─────────────────────────────────────────── */}
      {!result && !processing && !error && (
        <Card>
          <CardHeader>
            <CardTitle>Upload Food Label</CardTitle>
            <CardDescription>Supported formats: JPEG, PNG, WEBP, HEIC (max 20 MB)</CardDescription>
          </CardHeader>
          <CardContent>
            <div
              onDrop={handleDrop}
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              className={`relative border-2 border-dashed rounded-lg p-16 text-center transition-colors ${
                isDragging ? 'border-[#1A3A6B] bg-blue-50' : 'border-slate-300 hover:border-slate-400'
              }`}
            >
              <input
                type="file"
                accept="image/*"
                onChange={handleFileSelect}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
              <div className="flex flex-col items-center space-y-3">
                <Upload className="w-12 h-12 text-slate-400" />
                <div>
                  <p className="font-medium text-slate-900">Drag and drop an image here</p>
                  <p className="text-sm text-slate-500 mt-1">or click to select</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Processing ───────────────────────────────────────────── */}
      {processing && (
        <Card>
          <CardContent className="py-10">
            <div className="flex flex-col items-center text-center space-y-5">
              {previewUrl && (
                <img
                  src={previewUrl}
                  alt={file?.name ?? 'preview'}
                  className="max-h-48 rounded-lg border border-slate-200 object-contain"
                />
              )}
              <div className="w-full max-w-md space-y-2">
                <Progress value={progress} className="h-2" />
                <p className="text-sm text-slate-600">{stageLabel}</p>
                <p className="text-xs text-slate-400">Na cloud pode demorar 1–3 minutos (CPU). Aguarda…</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Error ────────────────────────────────────────────────── */}
      {error && !processing && (
        <Card>
          <CardContent className="py-6">
            <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
              <XCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-medium text-red-900 text-sm">Classification failed</p>
                <p className="text-xs text-red-700 mt-1">{error}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Result page ──────────────────────────────────────────── */}
      {showResultPage && result && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main column */}
          <div className="lg:col-span-2 space-y-6">
            {result.requires_human_review ? (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-start gap-2">
                <AlertCircle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium text-amber-900 text-sm">Flagged for Human Review</p>
                  <p className="text-xs text-amber-700 mt-0.5">
                    Confidence is {result.confidence.toUpperCase()} — requires supervisor validation
                  </p>
                </div>
              </div>
            ) : (
              <div className="bg-green-50 border border-green-200 rounded-lg p-3 flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-green-600 flex-shrink-0" />
                <p className="text-sm font-medium text-green-900">High confidence — no review required</p>
              </div>
            )}

            <Card>
              <CardContent className="pt-6 space-y-4">
                <div>
                  <FieldLabel>FoodEx2 Code</FieldLabel>
                  <p className="text-2xl font-mono font-semibold text-slate-900 mt-1">{result.base_term_code}</p>
                </div>
                <div>
                  <FieldLabel>Taxonomy Description</FieldLabel>
                  <p className="text-sm text-slate-700 mt-1">{result.base_term_label}</p>
                </div>
                <div>
                  <FieldLabel>Confidence Level</FieldLabel>
                  <Badge className={`mt-1 ${CONFIDENCE_STYLES[result.confidence] ?? ''}`}>
                    {result.confidence.toUpperCase()}
                  </Badge>
                </div>
              </CardContent>
            </Card>

            {(result.facets_readable?.length ?? 0) > 0 && (
              <Card>
                <CardHeader><CardTitle className="text-base">Facets (FoodEx2)</CardTitle></CardHeader>
                <CardContent className="space-y-1">
                  {result.facets_readable.map((f) => (
                    <div key={f.group} className="flex items-baseline gap-3 text-sm border border-slate-200 rounded px-3 py-1.5 bg-slate-50">
                      <span className="text-xs font-semibold text-slate-500 min-w-[140px]">{f.group_label}</span>
                      <span className="text-slate-800">{f.label ?? '—'}</span>
                      <span className="text-xs text-slate-400 font-mono ml-auto">{f.group}·{f.code}</span>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader><CardTitle className="text-base">Reasoning</CardTitle></CardHeader>
              <CardContent>
                <p className="text-sm text-slate-600 whitespace-pre-wrap break-words">{result.reasoning}</p>
              </CardContent>
            </Card>

            {result.ocr_text && (
              <Card>
                <CardHeader><CardTitle className="text-base">Extracted Text (OCR)</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-xs text-slate-600 bg-slate-50 p-3 rounded border border-slate-200 whitespace-pre-wrap break-words">
                    {result.ocr_text}
                  </p>
                </CardContent>
              </Card>
            )}

            {result.retrieved_sources?.length > 0 && (
              <Card>
                <CardHeader><CardTitle className="text-base">Retrieved Sources (RAG)</CardTitle></CardHeader>
                <CardContent>
                  <ul className="space-y-1">
                    {result.retrieved_sources.map((s, i) => (
                      <li key={i} className="text-xs text-slate-600 bg-slate-50 border border-slate-200 rounded px-2 py-1 truncate" title={s}>
                        {s}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Sidebar: image + metadata */}
          <div className="space-y-6">
            {previewUrl && (
              <Card>
                <CardHeader><CardTitle className="text-base">Submitted Image</CardTitle></CardHeader>
                <CardContent>
                  <img src={previewUrl} alt="Submitted label" className="w-full rounded-lg border border-slate-200 object-contain bg-slate-50" />
                  <p className="text-xs text-slate-400 mt-2 truncate" title={file?.name}>{file?.name}</p>
                </CardContent>
              </Card>
            )}
            <Card>
              <CardHeader><CardTitle className="text-base">Details</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-xs text-slate-500">
                <div><span className="font-semibold text-slate-600">ID:</span> <span className="font-mono break-all">{result.classification_id}</span></div>
                <div><span className="font-semibold text-slate-600">Time:</span> {new Date(result.timestamp).toLocaleString()}</div>
                <div><span className="font-semibold text-slate-600">Duration:</span> {result.total_time_ms.toFixed(0)} ms</div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{children}</p>;
}
