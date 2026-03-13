# Antigravity Landing

A React + Vite landing page ready for deployment on Vercel.

## Local Development

```bash
npm install
npm run dev
```

The app will start on the local Vite development server.

## Production Build

```bash
npm run build
npm run preview
```

The production-ready static build is generated in `dist/`.

## Vercel Deployment

The repository already includes `vercel.json` with explicit settings:

- framework: `vite`
- build command: `npm run build`
- output directory: `dist`

### Via the Vercel UI

1. Import the repository into Vercel.
2. Set the Root Directory to `antigravity-landing` if this is a monorepo.
3. Vercel will pick up the build settings from `vercel.json`.
4. Click Deploy.

### Via the Vercel CLI

```bash
npm i -g vercel
vercel
vercel --prod
```

If the project is deployed from a monorepo root, run these commands from inside the `antigravity-landing` directory.

## Routing

Navigation in the app uses hash routes (`#product`, `#use-cases`, and so on), so no additional SPA rewrite is required for Vercel.
