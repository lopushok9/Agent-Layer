# Antigravity Landing

Лендинг на React + Vite, готовый к деплою на Vercel.

## Локальный запуск

```bash
npm install
npm run dev
```

Приложение поднимется на локальном Vite dev server.

## Продакшен-сборка

```bash
npm run build
npm run preview
```

Готовый статический билд складывается в `dist/`.

## Деплой на Vercel

В репозитории уже добавлен [`vercel.json`](/Users/yuriytsygankov/Documents/openclaw_skill/antigravity-landing/vercel.json) с явной конфигурацией:

- framework: `vite`
- build command: `npm run build`
- output directory: `dist`

### Через UI Vercel

1. Импортируй репозиторий в Vercel.
2. Укажи Root Directory: `antigravity-landing`, если репозиторий монорепозиторный.
3. Build settings Vercel подтянет из `vercel.json`.
4. Нажми Deploy.

### Через Vercel CLI

```bash
npm i -g vercel
vercel
vercel --prod
```

Если проект деплоится из корня монорепозитория, запускай команды внутри директории `antigravity-landing`.

## Маршрутизация

Навигация в приложении построена через hash routes (`#product`, `#use-cases` и т.д.), поэтому отдельный SPA rewrite для Vercel не требуется.
