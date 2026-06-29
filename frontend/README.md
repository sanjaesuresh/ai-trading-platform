# Frontend — Research Terminal

Minimal React visualizer for simulated backtest results.

**This UI displays simulated backtests on historical data only. It is not
financial advice and implies no future profitability.**

## Setup

```bash
npm install
```

## Development

```bash
npm run dev
```

Opens at <http://localhost:5173>.

## Build

```bash
npm run build
```

Runs TypeScript type-check then Vite production build. Output in `dist/`.

## API base URL

The frontend calls the backend at `http://localhost:8000` by default. To
override, set `VITE_API_BASE_URL` before running:

```bash
VITE_API_BASE_URL=http://my-backend:8000 npm run dev
```

Or add it to a `.env.local` file (not committed):

```
VITE_API_BASE_URL=http://localhost:8000
```
