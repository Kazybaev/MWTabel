# Tabel Frontend

React frontend for the `Tabel` platform.

## Stack

- React
- Vite
- Hash-based routing
- JWT auth against the Django API

## Run in development

```powershell
cd d:\Tabel\frontend
npm install
npm run dev
```

The dev server runs on `http://127.0.0.1:5173/` and proxies `/api` to the Django backend on `http://127.0.0.1:8000/`.

## Build

```powershell
cd d:\Tabel\frontend
npm run build
```

## Main folders

- `src/pages` - app screens
- `src/components` - shared UI pieces
- `src/lib` - API client, router and formatting helpers
