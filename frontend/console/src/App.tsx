import { useQueryClient } from "@tanstack/react-query";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useLiveStream } from "./api/stream";
import { useAuth } from "./auth/AuthContext";
import { LoginPage } from "./auth/LoginPage";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { AdminPage } from "./pages/AdminPage";
import { AlertsPage } from "./pages/AlertsPage";
import { DataPage } from "./pages/DataPage";
import { DriftPage } from "./pages/DriftPage";
import { FleetPage } from "./pages/FleetPage";
import { ModelsPage } from "./pages/ModelsPage";
import { NotFound } from "./pages/NotFound";
import { TurbinePage } from "./pages/TurbinePage";
import { TurbinesPage } from "./pages/TurbinesPage";

export function App() {
  const { user, loading } = useAuth();
  const location = useLocation();
  const qc = useQueryClient();
  useLiveStream(qc, !!user);

  if (loading) return <div style={{ padding: 40 }}><Loading label="Restoring session" /></div>;
  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location.pathname + location.search }} />} />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route path="/login" element={<Navigate to={(location.state as { from?: string } | null)?.from ?? "/"} replace />} />
      <Route element={<Layout />}>
        <Route index element={<FleetPage />} />
        <Route path="turbines" element={<TurbinesPage />} />
        <Route path="turbines/:id" element={<TurbinePage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="drift" element={<DriftPage />} />
        <Route path="data" element={<DataPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
