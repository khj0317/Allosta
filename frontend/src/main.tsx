import { StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import type { Role } from './api';
import { AuthProvider, homeFor, useAuth } from './auth';
import { Layout } from './components/Layout';
import { Spinner } from './components/ui';
import { Dashboard } from './pages/admin/Dashboard';
import { BookConsultation } from './pages/customer/BookConsultation';
import { BookingDetail } from './pages/customer/BookingDetail';
import { MyBookings } from './pages/customer/MyBookings';
import { MyResults } from './pages/customer/MyResults';
import { Notifications } from './pages/customer/Notifications';
import { ResultView } from './pages/customer/ResultView';
import { Login } from './pages/Login';
import { Signup } from './pages/Signup';
import { ConsultWorkspace } from './pages/staff/ConsultWorkspace';
import { SlotManager } from './pages/staff/SlotManager';
import { StaffSchedule } from './pages/staff/StaffSchedule';
import './styles.css';

function Guard({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to="/login" replace />;
  if (!roles.includes(user.role)) return <Navigate to={homeFor(user)} replace />;
  return <>{children}</>;
}

function Home() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  return <Navigate to={user ? homeFor(user) : '/login'} replace />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/" element={<Home />} />
          <Route element={<Layout />}>
            <Route path="/my" element={<Guard roles={['CUSTOMER']}><MyResults /></Guard>} />
            <Route path="/my/results/:id" element={<Guard roles={['CUSTOMER']}><ResultView /></Guard>} />
            <Route path="/my/book" element={<Guard roles={['CUSTOMER']}><BookConsultation /></Guard>} />
            <Route path="/my/bookings" element={<Guard roles={['CUSTOMER']}><MyBookings /></Guard>} />
            <Route path="/my/bookings/:id" element={<Guard roles={['CUSTOMER']}><BookingDetail /></Guard>} />
            <Route path="/my/notifications" element={<Guard roles={['CUSTOMER']}><Notifications /></Guard>} />

            <Route path="/staff" element={<Guard roles={['COUNSELOR']}><StaffSchedule /></Guard>} />
            <Route path="/staff/slots" element={<Guard roles={['COUNSELOR']}><SlotManager /></Guard>} />
            <Route path="/staff/bookings/:id" element={<Guard roles={['COUNSELOR', 'ADMIN']}><ConsultWorkspace /></Guard>} />

            <Route path="/admin" element={<Guard roles={['ADMIN']}><Dashboard /></Guard>} />
            <Route path="/admin/bookings" element={<Guard roles={['ADMIN']}><StaffSchedule /></Guard>} />
            <Route path="/admin/slots" element={<Guard roles={['ADMIN']}><SlotManager /></Guard>} />
          </Route>
          <Route path="*" element={<Home />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>,
);
