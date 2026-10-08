import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { CircleLayout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { useAuth } from "./lib/auth";
import Alerts from "./pages/Alerts";
import Check from "./pages/Check";
import CircleHome from "./pages/CircleHome";
import Circles from "./pages/Circles";
import Hugh from "./pages/Hugh";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";
import Training from "./pages/Training";
import Voices from "./pages/Voices";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { me, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="mx-auto max-w-md p-10"><Spinner /></div>;
  if (!me) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return children;
}

export default function App() {
  return (
    <>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-xl focus:bg-ink focus:px-4 focus:py-2 focus:text-white">
        Skip to content
      </a>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<RequireAuth><Circles /></RequireAuth>} />
        <Route path="/onboarding" element={<RequireAuth><Onboarding /></RequireAuth>} />
        <Route path="/c/:circleId" element={<RequireAuth><CircleLayout /></RequireAuth>}>
          <Route index element={<CircleHome />} />
          <Route path="voices" element={<Voices />} />
          <Route path="training" element={<Training />} />
          <Route path="check" element={<Check />} />
          <Route path="hugh" element={<Hugh />} />
          <Route path="alerts" element={<Alerts />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
