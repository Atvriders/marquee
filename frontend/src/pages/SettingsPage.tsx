import { SettingsForm } from "../components/SettingsForm";
import { WatchdogPanel } from "../components/WatchdogPanel";

export function SettingsPage() {
  return (
    <section className="settings-page">
      <h2>Settings</h2>
      <SettingsForm />
      <h2>Jellyfin health</h2>
      <WatchdogPanel />
    </section>
  );
}
