import { useEffect, useState } from 'react';
import { ShieldCheck, RefreshCw, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { getAudit } from '../../api/client';
import type { AuditItem } from '../../types/classification';

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function AuditLogs() {
  const [logs, setLogs] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setLogs(await getAudit());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao carregar a auditoria');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900 mb-1">Audit Logs</h2>
          <p className="text-sm text-slate-600">
            Tamper-evident, HMAC-chained event log (EU AI Act traceability)
          </p>
        </div>
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-4">
          <AlertCircle className="w-4 h-4" />
          <span>{error}</span>
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-green-600" />
            <div>
              <CardTitle>Audit Trail</CardTitle>
              <CardDescription>
                {loading ? 'Loading…' : `${logs.length} entries`}
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Timestamp</TableHead>
                <TableHead>Event</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Entry ID</TableHead>
                <TableHead>HMAC</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!loading && logs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-slate-500 py-8">
                    No audit entries yet.
                  </TableCell>
                </TableRow>
              )}
              {logs.map((log) => (
                <TableRow key={log.entry_id}>
                  <TableCell className="text-sm whitespace-nowrap">{formatDate(log.timestamp)}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-slate-700 border-slate-300">
                      {log.event_type ?? '—'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm">{log.user_id ?? '—'}</TableCell>
                  <TableCell className="font-mono text-xs text-slate-500">
                    {log.entry_id.slice(0, 8)}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-slate-500" title={log.hmac ?? ''}>
                    {log.hmac ? `${log.hmac.slice(0, 12)}…` : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
