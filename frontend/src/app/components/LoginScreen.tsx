import { useState } from 'react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';

interface LoginScreenProps {
  onLogin: (role: string) => void;
}

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Demo logic: assign role based on username
    if (username.toLowerCase().includes('admin')) {
      onLogin('administrator');
    } else if (username.toLowerCase().includes('supervisor')) {
      onLogin('supervisor');
    } else if (username.toLowerCase().includes('auditor')) {
      onLogin('auditor');
    } else {
      onLogin('inspector');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F5F7FA]">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader className="space-y-3 text-center pb-6">
          <div className="mx-auto w-16 h-16 bg-[#1A3A6B] rounded-lg flex items-center justify-center mb-2">
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M16 8V16L20 20" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="16" cy="16" r="10" stroke="white" strokeWidth="2"/>
            </svg>
          </div>
          <CardTitle className="text-2xl">IDRISK2</CardTitle>
          <CardDescription className="text-sm">
            AI-Powered Food Product Classification System<br />
            European Food Safety Authority (EFSA) FoodEx2 Taxonomy
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                type="text"
                placeholder="Enter your username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full bg-[#1A3A6B] hover:bg-[#2A4A7B]">
              Sign In
            </Button>
            <p className="text-xs text-center text-slate-500 mt-4">
              Demo: Use "inspector", "supervisor", "administrator", or "auditor" as username
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
