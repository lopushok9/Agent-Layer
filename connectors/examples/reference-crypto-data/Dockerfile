FROM node:24-alpine AS build

WORKDIR /app/connectors
COPY connectors/package.json connectors/package-lock.json ./
COPY connectors/sdk-typescript ./sdk-typescript
COPY connectors/conformance ./conformance
COPY connectors/templates/read-only ./templates/read-only
COPY connectors/examples/reference-crypto-data ./examples/reference-crypto-data
RUN npm ci
RUN npm run build --workspace @agentlayer.tech/connector-sdk
RUN npm run build --workspace @agentlayer.tech/reference-crypto-data-connector

FROM node:24-alpine

ENV NODE_ENV=production
WORKDIR /app/connectors
COPY --from=build --chown=node:node /app/connectors /app/connectors
USER node
EXPOSE 3000

CMD ["npm", "run", "start", "--workspace", "@agentlayer.tech/reference-crypto-data-connector"]
