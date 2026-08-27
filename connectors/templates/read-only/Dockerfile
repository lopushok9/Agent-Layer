FROM node:24-alpine AS build
WORKDIR /app/connectors
COPY connectors/ /app/connectors/
RUN npm ci && npm run build --workspace @agentlayer.tech/read-only-connector-template

FROM node:24-alpine
ENV NODE_ENV=production
WORKDIR /app/connectors
COPY --from=build /app /app
USER node
CMD ["npm", "run", "start", "--workspace", "@agentlayer.tech/read-only-connector-template"]
