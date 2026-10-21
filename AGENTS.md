# mini-ki – Regeln für Agenten

- **Kein Mercury (Wudu 2026-10-22):** Mercury (`inception/mercury-*`, auch über opencode) wird gar nicht mehr zum Bauen, Prüfen oder Reviewen benutzt – es macht alles kaputt. Gebaut und geprüft wird nur noch mit Grok über die Cursor-CLI. Kein Label `stufe:mercury`/`stufe-mercury` mehr setzen; Teil-Issues bekommen `stufe:cursor`.
- Allgemeine Arbeitsweise wie in `Genjuzu/avataribot` (`AGENTS.md`): ein Branch pro Issue (`issues/<nr>-<kurz>`), Commit-Meldungen auf Deutsch mit `#nr`, kein Force-Push, keine `.env`/Secrets, kein Fremdcode.
