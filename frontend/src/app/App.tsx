import { useState } from 'react';
import { LoginScreen } from './components/LoginScreen';
import { InspectorSubmission } from './components/InspectorSubmission';
import { InspectorHistory } from './components/InspectorHistory';
import { SupervisorDashboard } from './components/SupervisorDashboard';
import { AdministratorUsers } from './components/AdministratorUsers';
import { AuditLogs } from './components/AuditLogs';
import { Home, Upload, History, BarChart3, Users, FileText, LogOut, Menu } from 'lucide-react';
import { Button } from './components/ui/button';
import { Avatar, AvatarFallback } from './components/ui/avatar';
import { Sheet, SheetContent, SheetTitle, SheetDescription } from './components/ui/sheet';

type UserRole = 'inspector' | 'supervisor' | 'administrator' | 'auditor';

type Screen =
  | 'submission'
  | 'history'
  | 'dashboard'
  | 'users'
  | 'audit';

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [userRole, setUserRole] = useState<UserRole>('inspector');
  const [currentScreen, setCurrentScreen] = useState<Screen>('submission');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const handleLogin = (role: string) => {
    setUserRole(role as UserRole);
    setIsLoggedIn(true);
    // Set initial screen based on role
    if (role === 'supervisor') {
      setCurrentScreen('dashboard');
    } else if (role === 'administrator') {
      setCurrentScreen('users');
    } else {
      setCurrentScreen('submission');
    }
  };

  const handleLogout = () => {
    setIsLoggedIn(false);
    setUserRole('inspector');
    setCurrentScreen('submission');
  };

  if (!isLoggedIn) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  const navigationItems = {
    inspector: [
      { id: 'submission' as Screen, label: 'Submit Image', icon: Upload },
      { id: 'history' as Screen, label: 'Results History', icon: History }
    ],
    supervisor: [
      { id: 'dashboard' as Screen, label: 'Dashboard', icon: BarChart3 },
      { id: 'history' as Screen, label: 'All Results', icon: History },
      { id: 'audit' as Screen, label: 'Audit Logs', icon: FileText }
    ],
    administrator: [
      { id: 'dashboard' as Screen, label: 'Dashboard', icon: BarChart3 },
      { id: 'users' as Screen, label: 'User Management', icon: Users },
      { id: 'history' as Screen, label: 'All Results', icon: History },
      { id: 'audit' as Screen, label: 'Audit Logs', icon: FileText }
    ],
    auditor: [
      { id: 'history' as Screen, label: 'Results', icon: History },
      { id: 'audit' as Screen, label: 'Audit Logs', icon: FileText }
    ]
  };

  const navItems = navigationItems[userRole];

  const SidebarContent = () => (
    <>
      <div className="p-6 border-b border-slate-200">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-[#1A3A6B] rounded-lg flex items-center justify-center flex-shrink-0">
            <svg width="24" height="24" viewBox="0 0 32 32" fill="none">
              <path d="M16 8V16L20 20" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="16" cy="16" r="10" stroke="white" strokeWidth="2"/>
            </svg>
          </div>
          <div className="min-w-0">
            <h1 className="font-bold text-lg text-slate-900">IDRISK2</h1>
            <p className="text-xs text-slate-500 truncate">Food Classification System</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 p-4">
        <div className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentScreen === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  setCurrentScreen(item.id);
                  setMobileMenuOpen(false);
                }}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-[#1A3A6B] text-white'
                    : 'text-slate-700 hover:bg-slate-100'
                }`}
              >
                <Icon className="w-5 h-5" />
                {item.label}
              </button>
            );
          })}
        </div>
      </nav>

      <div className="p-4 border-t border-slate-200">
        <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg mb-3">
          <Avatar className="h-8 w-8">
            <AvatarFallback className="bg-[#1A3A6B] text-white text-xs">
              {userRole.charAt(0).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-900 truncate">
              {userRole.charAt(0).toUpperCase() + userRole.slice(1)}
            </p>
            <p className="text-xs text-slate-500">user@efsa.europa.eu</p>
          </div>
        </div>
        <Button
          onClick={handleLogout}
          variant="outline"
          className="w-full justify-start"
          size="sm"
        >
          <LogOut className="w-4 h-4 mr-2" />
          Sign Out
        </Button>
      </div>
    </>
  );

  return (
    <div className="flex h-screen bg-[#F5F7FA]">
      {/* Desktop Sidebar */}
      <aside className="hidden lg:flex lg:flex-col w-64 bg-white border-r border-slate-200">
        <SidebarContent />
      </aside>

      {/* Mobile Sidebar */}
      <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
        <SheetContent side="left" className="w-64 p-0">
          <SheetTitle className="sr-only">Navigation Menu</SheetTitle>
          <SheetDescription className="sr-only">
            Main navigation for IDRISK2 application
          </SheetDescription>
          <div className="flex flex-col h-full">
            <SidebarContent />
          </div>
        </SheetContent>
      </Sheet>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Mobile Header */}
        <header className="lg:hidden bg-white border-b border-slate-200 p-4 flex items-center gap-3">
          <button
            onClick={() => setMobileMenuOpen(true)}
            className="lg:hidden p-2 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-[#1A3A6B] rounded-lg flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 32 32" fill="none">
                <path d="M16 8V16L20 20" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                <circle cx="16" cy="16" r="10" stroke="white" strokeWidth="2"/>
              </svg>
            </div>
            <h1 className="font-bold text-slate-900">IDRISK2</h1>
          </div>
        </header>

        {/* Content Area */}
        <div className="flex-1 overflow-auto">
          <div className="max-w-7xl mx-auto p-6">
            {currentScreen === 'submission' && <InspectorSubmission />}
            {currentScreen === 'history' && <InspectorHistory />}
            {currentScreen === 'dashboard' && <SupervisorDashboard />}
            {currentScreen === 'users' && <AdministratorUsers />}
            {currentScreen === 'audit' && <AuditLogs />}
          </div>
        </div>
      </main>
    </div>
  );
}