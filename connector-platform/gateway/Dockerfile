FROM node:24-bookworm-slim

WORKDIR /app
COPY --chown=node:node package.json ./
COPY --chown=node:node src ./src

ENV NODE_ENV=production
USER node
EXPOSE 3000

CMD ["node", "src/server.mjs"]

