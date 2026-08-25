# SIH_26
Loan Recommendation for Marginalized Clients
# Scheme Sarathi — SIH26092 Prototype

## What's here
- `backend/` — Node/Express API (3 endpoints, no database, data lives in JSON files)
- `frontend/` — plain HTML/JS/Tailwind (no build step, just open the file)

## How to run (any teammate, any device)

**Backend:**
```
cd backend
npm install
npm start
```
Runs on http://localhost:4000. Test it's alive: `curl http://localhost:4000/api/schemes`

**Frontend:**
Just open `frontend/index.html` directly in Chrome (double-click it, or use the
VS Code "Live Server" extension for auto-reload). It calls the backend at
`http://localhost:4000` — so the backend must be running first.

No database, no API keys, no build tooling — this is intentional so all 5 of
you can clone and run this in under 2 minutes on your own laptop.

## What's real vs. mocked right now
- **Recommend logic**: real rule engine, reads `backend/data/schemes.json`
- **EMI calculator**: real reducing-balance math with moratorium capitalization
- **Partner locator**: real haversine distance + NPA filtering, but the 6
  partners in `backend/data/partners.json` are made-up sample data, not
  scraped from an actual SCA/bank directory
- **Voice input**: real Web Speech API (Chrome only), simple keyword+number
  parsing — works for clear sentences like "cost is 8 lakh income is 3 lakh
  for business", will need hardening for messier phrasing
- **Language switching for voice**: currently hardcoded to `en-IN` in
  `app.js` — change `recognition.lang` to `hi-IN`, `kn-IN` etc. to test other
  languages, or wire up a dropdown

## Where to go next
1. Add 15-20 more real partner entries (or scrape a real directory) so the
   locator demo doesn't look thin
2. Add a language dropdown that both sets `recognition.lang` and translates
   the reasoning/result text (Bhashini or Google Translate API)
3. Move to a real DB (Postgres) once the data outgrows JSON files — not
   urgent for the demo
4. Polish UI states: loading spinners, empty states, mobile responsiveness

## Git workflow reminder
- `main` stays demo-able at all times
- Work on feature branches (`feature/partner-data`, `feature/voice-lang`, etc.)
- Don't commit `node_modules/` — a `.gitignore` is included
