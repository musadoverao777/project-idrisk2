import { useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { CheckCircle2, XCircle, AlertCircle, RefreshCw } from 'lucide-react';
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { getStats, getReviews, decideReview } from '../../api/client';
import type { DashboardStats, ReviewItem } from '../../types/classification';

const CONF_COLORS: Record<string, string> = { High: '#10B981', Medium: '#F59E0B', Low: '#EF4444' };

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function SupervisorDashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [queue, setQueue] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [s, q] = await Promise.all([getStats(), getReviews('pending')]);
      setStats(s);
      setQueue(q);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao carregar o dashboard');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleDecision(id: string, status: 'approved' | 'rejected') {
    setBusyId(id);
    try {
      await decideReview(id, { status });
      setQueue((q) => q.filter((item) => item.classification_id !== id));
      const s = await getStats();
      setStats(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao registar a decisão');
    } finally {
      setBusyId(null);
    }
  }

  const getConfidenceBadge = (confidence: string) => {
    const variants: Record<string, string> = {
      high: 'bg-green-100 text-green-800 border-green-300',
      medium: 'bg-amber-100 text-amber-800 border-amber-300',
      low: 'bg-red-100 text-red-800 border-red-300',
    };
    return variants[confidence.toLowerCase()] ?? 'bg-slate-100 text-slate-600 border-slate-300';
  };

  const confidenceData = stats
    ? [
        { name: 'High', value: stats.confidence.high, color: CONF_COLORS.High },
        { name: 'Medium', value: stats.confidence.medium, color: CONF_COLORS.Medium },
        { name: 'Low', value: stats.confidence.low, color: CONF_COLORS.Low },
      ].filter((d) => d.value > 0)
    : [];
  const weeklyData = stats?.weekly ?? [];
  const todayCount = weeklyData.length ? weeklyData[weeklyData.length - 1].classifications : 0;
  const weekCount = weeklyData.reduce((sum, d) => sum + d.classifications, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900 mb-1">Supervisor Dashboard</h2>
          <p className="text-sm text-slate-600">Monitor system activity and manage review queue</p>
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

      {/* Metrics Overview */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-3"><CardDescription>Today's Classifications</CardDescription></CardHeader>
          <CardContent><div className="text-3xl font-bold text-slate-900">{todayCount}</div></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3"><CardDescription>This Week</CardDescription></CardHeader>
          <CardContent><div className="text-3xl font-bold text-slate-900">{weekCount}</div></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3"><CardDescription>Pending Reviews</CardDescription></CardHeader>
          <CardContent>
            <div className="flex items-baseline gap-2">
              <div className="text-3xl font-bold text-amber-600">{stats?.pending_reviews ?? 0}</div>
              <AlertCircle className="w-5 h-5 text-amber-600" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3"><CardDescription>Total Classifications</CardDescription></CardHeader>
          <CardContent><div className="text-3xl font-bold text-slate-900">{stats?.total ?? 0}</div></CardContent>
        </Card>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Confidence Distribution</CardTitle>
            <CardDescription>Classification confidence levels (all records)</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={confidenceData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                  outerRadius={80}
                  dataKey="value"
                  key="pie-confidence"
                >
                  {confidenceData.map((entry) => (
                    <Cell key={`cell-${entry.name}`} fill={entry.color} />
                  ))}
                </Pie>
                <Legend key="legend" />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Weekly Activity</CardTitle>
            <CardDescription>Classifications per day (last 7 days)</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={weeklyData}>
                <CartesianGrid strokeDasharray="3 3" key="grid" />
                <XAxis dataKey="day" key="xaxis" />
                <YAxis allowDecimals={false} key="yaxis" />
                <Tooltip key="tooltip" />
                <Bar dataKey="classifications" fill="#1A3A6B" key="bar-classifications" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Review Queue */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Review Queue</CardTitle>
              <CardDescription>Items requiring human validation</CardDescription>
            </div>
            <Badge variant="outline" className="text-amber-700 border-amber-300 bg-amber-50">
              {queue.length} pending
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Submitted By</TableHead>
                <TableHead>Time</TableHead>
                <TableHead>Extracted Text (OCR)</TableHead>
                <TableHead>Proposed Code</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!loading && queue.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-sm text-slate-500 py-8">
                    No items pending review. 🎉
                  </TableCell>
                </TableRow>
              )}
              {queue.map((item) => (
                <TableRow key={item.classification_id}>
                  <TableCell className="font-mono text-xs font-medium">
                    {item.classification_id.slice(0, 8)}
                  </TableCell>
                  <TableCell className="text-sm">{item.submitted_by ?? '—'}</TableCell>
                  <TableCell className="text-sm whitespace-nowrap">{formatDate(item.timestamp)}</TableCell>
                  <TableCell className="max-w-xs">
                    <p className="text-xs text-slate-600 truncate" title={item.ocr_text}>
                      {item.ocr_text || '—'}
                    </p>
                  </TableCell>
                  <TableCell>
                    <div>
                      <p className="font-mono text-sm font-medium">{item.base_term_code}</p>
                      <p className="text-xs text-slate-500 mt-0.5">{item.base_term_label}</p>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge className={getConfidenceBadge(item.confidence)}>
                      {item.confidence.toUpperCase()}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busyId === item.classification_id}
                        onClick={() => handleDecision(item.classification_id, 'approved')}
                        className="h-8 w-8 p-0 border-green-300 text-green-700 hover:bg-green-50"
                        title="Approve"
                      >
                        <CheckCircle2 className="w-4 h-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busyId === item.classification_id}
                        onClick={() => handleDecision(item.classification_id, 'rejected')}
                        className="h-8 w-8 p-0 border-red-300 text-red-700 hover:bg-red-50"
                        title="Reject"
                      >
                        <XCircle className="w-4 h-4" />
                      </Button>
                    </div>
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
