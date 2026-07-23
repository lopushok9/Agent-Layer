# AgentLayer Landing

A React + Vite site deployed on Vercel. Server-side onboarding routes live in
`api/` as Vercel Functions; secrets and PostgreSQL access never belong in
`src/`.

## Local Development

```bash
npm install
vercel dev
```

Copy `.env.example` to a local environment file and configure PostgreSQL plus at
least one OAuth provider. `vercel dev` is required when testing `/api/*`; plain
`npm run dev` only starts the Vite frontend.

Apply the Better Auth and welcome onboarding tables:

```bash
npm run db:migrate
```

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
2. Set the Root Directory to `landing`.
3. Vercel will pick up the build settings from `vercel.json`.
4. Click Deploy.

### Via the Vercel CLI

```bash
npm i -g vercel
vercel
vercel --prod
```

If the project is deployed from a monorepo root, run these commands from inside the `antigravity-landing` directory.

## Welcome onboarding backend

The first implementation accepts a successfully authenticated GitHub **or** X
account. It intentionally has no account-age, follower, repository, or activity
thresholds yet.

OAuth callbacks:

- `https://<origin>/api/auth/callback/github`
- `https://<origin>/api/auth/callback/twitter`

Invite binding:

- `POST /api/onboarding/bind-wallet`
- invite in `Authorization: Bearer ...`
- JSON body: `{ "address": "0x..." }`

Production and preview should use separate databases, auth secrets, OAuth apps,
and campaign IDs. Never expose `DATABASE_URL`, OAuth secrets, or
`BETTER_AUTH_SECRET` through a `VITE_` environment variable.
