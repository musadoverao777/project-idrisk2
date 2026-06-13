import { useEffect, useState } from 'react';
import { Filter, Search, RefreshCw, AlertCircle } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import { Button } from './ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { getHistory } from '../../api/client';
import type { HistoryItem } from '../../types/classification';

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function InspectorHistory() {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [records, setRecords] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await getHistory();
      setRecords(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao carregar o histórico');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const filteredHistory = records.filter((record) => {
    const term = searchTerm.toLowerCase();
    const matchesSearch =
      record.base_term_code.toLowerCase().includes(term) ||
      record.base_term_label.toLowerCase().includes(term);
    const matchesStatus = statusFilter === 'all' || record.review_status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getConfidenceBadge = (confidence: string) => {
    const variants: Record<string, string> = {
      high: 'bg-green-100 text-green-800 border-green-300',
      medium: 'bg-amber-100 text-amber-800 border-amber-300',
      low: 'bg-red-100 text-red-800 border-red-300',
    };
    return variants[confidence.toLowerCase()] ?? 'bg-slate-100 text-slate-600 border-slate-300';
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, string> = {
      pending: 'bg-amber-100 text-amber-800 border-amber-300',
      approved: 'bg-green-100 text-green-800 border-green-300',
      rejected: 'bg-red-100 text-red-800 border-red-300',
      none: 'bg-slate-100 text-slate-600 border-slate-300',
    };
    const labels: Record<string, string> = {
      pending: 'Pending Review',
      approved: 'Approved',
      rejected: 'Rejected',
      none: 'No Review',
    };
    return {
      className: variants[status] ?? variants.none,
      label: labels[status] ?? status,
    };
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-slate-900 mb-1">Results History</h2>
        <p className="text-sm text-slate-600">View your past classification submissions</p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
            <div>
              <CardTitle>Classification Records</CardTitle>
              <CardDescription>
                {loading
                  ? 'Loading…'
                  : `${records.length} record${records.length === 1 ? '' : 's'} from the database`}
              </CardDescription>
            </div>
            <div className="flex gap-2 w-full sm:w-auto">
              <div className="relative flex-1 sm:flex-initial sm:w-64">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <Input
                  placeholder="Search by code or description..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-9"
                />
              </div>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-40">
                  <Filter className="w-4 h-4 mr-2" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Status</SelectItem>
                  <SelectItem value="none">No Review</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="approved">Approved</SelectItem>
                  <SelectItem value="rejected">Rejected</SelectItem>
                </SelectContent>
              </Select>
              <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Refresh">
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-4">
              <AlertCircle className="w-4 h-4" />
              <span>{error}</span>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date &amp; Time</TableHead>
                  <TableHead>Image</TableHead>
                  <TableHead>FoodEx2 Code</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Confidence</TableHead>
                  <TableHead>Review Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {!loading && filteredHistory.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-sm text-slate-500 py-8">
                      {records.length === 0
                        ? 'No classifications yet. Submit an image to get started.'
                        : 'No records match your filters.'}
                    </TableCell>
                  </TableRow>
                )}
                {filteredHistory.map((record) => {
                  const status = getStatusBadge(record.review_status);
                  return (
                    <TableRow key={record.id}>
                      <TableCell className="font-medium text-sm whitespace-nowrap">
                        {formatDate(record.timestamp)}
                      </TableCell>
                      <TableCell>
                        <div
                          className="w-12 h-12 bg-slate-200 rounded border border-slate-300 flex items-center justify-center"
                          title={record.image_hash ? `SHA-256: ${record.image_hash.slice(0, 12)}…` : undefined}
                        >
                          <span className="text-xs text-slate-500">IMG</span>
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-sm">{record.base_term_code}</TableCell>
                      <TableCell className="text-sm max-w-xs">{record.base_term_label}</TableCell>
                      <TableCell>
                        <Badge className={getConfidenceBadge(record.confidence)}>
                          {record.confidence.toUpperCase()}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge className={status.className}>{status.label}</Badge>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
