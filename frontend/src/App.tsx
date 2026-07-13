import { NavLink, Route, Routes } from "react-router-dom";
import { StatusBar } from "./components/StatusBar";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { DashboardPage } from "./pages/DashboardPage";
import { ActivityPage } from "./pages/ActivityPage";
import { SettingsPage } from "./pages/SettingsPage";

export function App() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="marquee-sign">
          <span className="bulb-row" aria-hidden="true" />
          <span className="brand">MARQUEE</span>
          <span className="bulb-row" aria-hidden="true" />
        </div>
        <nav className="app-nav">
          <NavLink to="/">Dashboard</NavLink>
          <NavLink to="/activity">Activity</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
        <ConnectionStatus />
      </header>
      <StatusBar />
      <main className="app-main">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
