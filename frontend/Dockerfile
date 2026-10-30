# Frontend: production Next.js server. The browser talks only to this server;
# /api is proxied to the backend (IAP_BACKEND_URL), so cookies stay same-origin.
FROM node:22-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG IAP_BACKEND_URL=http://backend:8000
ENV IAP_BACKEND_URL=${IAP_BACKEND_URL}
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
ARG IAP_BACKEND_URL=http://backend:8000
ENV IAP_BACKEND_URL=${IAP_BACKEND_URL}
COPY --from=build --chown=node:node /app/package.json /app/next.config.ts ./
# Full node_modules: next.config.ts is compiled at start-up.
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
USER node
EXPOSE 3000
CMD ["npm", "start"]
