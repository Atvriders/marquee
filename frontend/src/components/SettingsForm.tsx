import { useEffect, useState } from "react";
import { api } from "../api";
import type { Config } from "../types";

const ALL_SOURCES = ["upcoming", "now_playing", "popular", "trending_day", "trending_week"];

export function SettingsForm() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [message, setMessage] = useState<string>("");
  // Raw text of the sources input, decoupled from cfg.sources: re-deriving the
  // displayed value from a comma-split/filtered array on every keystroke snaps
  // the field back to its trimmed form mid-edit (e.g. a just-typed trailing
  // "," or " " gets stripped before the next character lands), corrupting
  // typed input. We keep the free-form text here and only parse it into
  // cfg.sources on save.
  const [sourcesText, setSourcesText] = useState<string>("");

  useEffect(() => {
    api
      .getSettings()
      .then((c) => {
        setCfg(c);
        setSourcesText(c.sources.join(", "));
      })
      .catch((e) => setMessage(String(e)));
  }, []);

  if (!cfg) return <p>Loading settings…</p>;

  const set = <K extends keyof Config>(k: K, v: Config[K]) =>
    setCfg({ ...cfg, [k]: v });

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage("Saving…");
    try {
      const sources = sourcesText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      // GET /api/settings masks secrets as "***"; don't resend an unchanged mask
      // or we'd overwrite the stored secret with the literal "***".
      const payload: Record<string, unknown> = { ...cfg, sources };
      for (const k of ["tmdb_token", "jellyfin_api_key", "jellyfin_pass"]) {
        if (payload[k] === "***") delete payload[k];
      }
      const saved = await api.updateSettings(payload as unknown as Config);
      setCfg(saved);
      setSourcesText(saved.sources.join(", "));
      setMessage("Saved.");
    } catch (err) {
      setMessage(String(err));
    }
  };

  const testJellyfin = async () => {
    setMessage("Testing Jellyfin…");
    try {
      const r = await api.testJellyfin();
      setMessage(r.ok ? "Jellyfin OK." : "Jellyfin test failed.");
    } catch (err) {
      setMessage(String(err));
    }
  };

  const runNow = async () => {
    setMessage("Triggering refresh…");
    try {
      await api.runNow();
      setMessage("Refresh started.");
    } catch (err) {
      setMessage(String(err));
    }
  };

  return (
    <form className="settings-form" onSubmit={save}>
      <fieldset>
        <legend>Sources</legend>
        <label>
          sources
          <input
            aria-label="sources"
            value={sourcesText}
            onChange={(e) => setSourcesText(e.target.value)}
          />
        </label>
        <small>Any of: {ALL_SOURCES.join(", ")}</small>
        <label>
          count
          <input
            aria-label="count"
            type="number"
            value={cfg.count}
            onChange={(e) => set("count", Number(e.target.value))}
          />
        </label>
        <label>
          region
          <input
            aria-label="region"
            value={cfg.region}
            onChange={(e) => set("region", e.target.value)}
          />
        </label>
        <label>
          language
          <input
            aria-label="language"
            value={cfg.language}
            onChange={(e) => set("language", e.target.value)}
          />
        </label>
      </fieldset>

      <fieldset>
        <legend>Format</legend>
        <label>
          container
          <select
            aria-label="container"
            value={cfg.container}
            onChange={(e) => set("container", e.target.value)}
          >
            <option value="mkv">mkv</option>
            <option value="mp4">mp4</option>
          </select>
        </label>
        <label>
          max_height
          <input
            aria-label="max_height"
            type="number"
            value={cfg.max_height}
            onChange={(e) => set("max_height", Number(e.target.value))}
          />
        </label>
      </fieldset>

      <fieldset>
        <legend>Schedule</legend>
        <label>
          refresh_cron
          <input
            aria-label="refresh_cron"
            value={cfg.refresh_cron}
            onChange={(e) => set("refresh_cron", e.target.value)}
          />
        </label>
        <label>
          reaper_cron
          <input
            aria-label="reaper_cron"
            value={cfg.reaper_cron}
            onChange={(e) => set("reaper_cron", e.target.value)}
          />
        </label>
        <label>
          grace_days
          <input
            aria-label="grace_days"
            type="number"
            value={cfg.grace_days}
            onChange={(e) => set("grace_days", Number(e.target.value))}
          />
        </label>
        <label>
          tz
          <input aria-label="tz" value={cfg.tz} onChange={(e) => set("tz", e.target.value)} />
        </label>
        <label>
          max_size_gb
          <input
            aria-label="max_size_gb"
            type="number"
            value={cfg.max_size_gb}
            onChange={(e) => set("max_size_gb", Number(e.target.value))}
          />
        </label>
      </fieldset>

      <fieldset>
        <legend>Jellyfin</legend>
        <label>
          jellyfin_url
          <input
            aria-label="jellyfin_url"
            value={cfg.jellyfin_url ?? ""}
            onChange={(e) => set("jellyfin_url", e.target.value || null)}
          />
        </label>
        <label>
          jellyfin_api_key
          <input
            aria-label="jellyfin_api_key"
            value={cfg.jellyfin_api_key ?? ""}
            onChange={(e) => set("jellyfin_api_key", e.target.value || null)}
          />
        </label>
        <label>
          jellyfin_user
          <input
            aria-label="jellyfin_user"
            value={cfg.jellyfin_user ?? ""}
            onChange={(e) => set("jellyfin_user", e.target.value || null)}
          />
        </label>
        <label>
          jellyfin_pass
          <input
            aria-label="jellyfin_pass"
            type="password"
            value={cfg.jellyfin_pass ?? ""}
            onChange={(e) => set("jellyfin_pass", e.target.value || null)}
          />
        </label>
        <button type="button" onClick={testJellyfin}>
          Test Jellyfin
        </button>
      </fieldset>

      <fieldset>
        <legend>Advanced</legend>
        <label>
          tmdb_token
          <input
            aria-label="tmdb_token"
            value={cfg.tmdb_token}
            onChange={(e) => set("tmdb_token", e.target.value)}
          />
        </label>
        <label>
          ytdlp_cookies
          <input
            aria-label="ytdlp_cookies"
            value={cfg.ytdlp_cookies ?? ""}
            onChange={(e) => set("ytdlp_cookies", e.target.value || null)}
          />
        </label>
        <label>
          ytdlp_proxy
          <input
            aria-label="ytdlp_proxy"
            value={cfg.ytdlp_proxy ?? ""}
            onChange={(e) => set("ytdlp_proxy", e.target.value || null)}
          />
        </label>
      </fieldset>

      <div className="settings-actions">
        <button type="submit">Save</button>
        <button type="button" onClick={runNow}>
          Run now
        </button>
        {message && <span className="settings-message">{message}</span>}
      </div>
    </form>
  );
}
