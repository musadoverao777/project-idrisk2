import { useEffect, useState } from 'react';
import { UserPlus, MoreVertical, UserX, RefreshCw, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from './ui/dialog';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './ui/dropdown-menu';
import { getUsers, createUser, setUserStatus } from '../../api/client';
import type { UserItem } from '../../types/classification';

export function AdministratorUsers() {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [newUser, setNewUser] = useState<{ username: string; email: string; role: string }>({
    username: '',
    email: '',
    role: 'inspector',
  });

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setUsers(await getUsers());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao carregar utilizadores');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const getRoleBadge = (role: string) => {
    const variants: Record<string, string> = {
      inspector: 'bg-blue-100 text-blue-800 border-blue-300',
      supervisor: 'bg-purple-100 text-purple-800 border-purple-300',
      administrator: 'bg-red-100 text-red-800 border-red-300',
      auditor: 'bg-green-100 text-green-800 border-green-300',
    };
    return variants[role] ?? 'bg-slate-100 text-slate-600 border-slate-300';
  };

  const getStatusBadge = (status: string) =>
    status === 'active'
      ? 'bg-green-100 text-green-800 border-green-300'
      : 'bg-slate-100 text-slate-600 border-slate-300';

  async function handleCreateUser() {
    setSaving(true);
    setError(null);
    try {
      const created = await createUser(newUser);
      setUsers((prev) => [created, ...prev]);
      setNewUser({ username: '', email: '', role: 'inspector' });
      setIsCreateDialogOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao criar utilizador');
    } finally {
      setSaving(false);
    }
  }

  async function handleDeactivateUser(userId: string) {
    try {
      await setUserStatus(userId, 'inactive');
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, status: 'inactive' } : u)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao desativar utilizador');
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900 mb-1">User Management</h2>
          <p className="text-sm text-slate-600">Manage system users and access permissions</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Refresh">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
          <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
            <DialogTrigger asChild>
              <Button className="bg-[#1A3A6B] hover:bg-[#2A4A7B]">
                <UserPlus className="w-4 h-4 mr-2" />
                Create New User
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create New User</DialogTitle>
                <DialogDescription>
                  Add a new user to the IDRISK2 system with the appropriate role.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label htmlFor="username">Username</Label>
                  <Input
                    id="username"
                    placeholder="e.g., j.doe"
                    value={newUser.username}
                    onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="j.doe@efsa.europa.eu"
                    value={newUser.email}
                    onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="role">Role</Label>
                  <Select
                    value={newUser.role}
                    onValueChange={(value: string) => setNewUser({ ...newUser, role: value })}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="inspector">Inspector</SelectItem>
                      <SelectItem value="supervisor">Supervisor</SelectItem>
                      <SelectItem value="administrator">Administrator</SelectItem>
                      <SelectItem value="auditor">Auditor</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-slate-500 mt-1">
                    {newUser.role === 'inspector' && 'Can submit images and view own results'}
                    {newUser.role === 'supervisor' && 'Can view all results, manage review queue, and access audit logs'}
                    {newUser.role === 'administrator' && 'Full system access including user and knowledge base management'}
                    {newUser.role === 'auditor' && 'Read-only access to audit logs and results'}
                  </p>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setIsCreateDialogOpen(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={handleCreateUser}
                  className="bg-[#1A3A6B] hover:bg-[#2A4A7B]"
                  disabled={!newUser.username || !newUser.email || saving}
                >
                  {saving ? 'Saving…' : 'Create User'}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-4">
          <AlertCircle className="w-4 h-4" />
          <span>{error}</span>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>System Users</CardTitle>
          <CardDescription>
            {users.filter((u) => u.status === 'active').length} active users • {users.length} total
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Username</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!loading && users.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-sm text-slate-500 py-8">
                    No users found.
                  </TableCell>
                </TableRow>
              )}
              {users.map((user) => (
                <TableRow key={user.id}>
                  <TableCell className="font-medium">{user.username}</TableCell>
                  <TableCell className="text-sm text-slate-600">{user.email ?? '—'}</TableCell>
                  <TableCell>
                    <Badge className={getRoleBadge(user.role)}>
                      {user.role.charAt(0).toUpperCase() + user.role.slice(1)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge className={getStatusBadge(user.status)}>
                      {user.status.charAt(0).toUpperCase() + user.status.slice(1)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-slate-600">{user.created_at ?? '—'}</TableCell>
                  <TableCell className="text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                          <MoreVertical className="w-4 h-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() => handleDeactivateUser(user.id)}
                          disabled={user.status === 'inactive'}
                          className="text-red-600"
                        >
                          <UserX className="w-4 h-4 mr-2" />
                          Deactivate
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
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
