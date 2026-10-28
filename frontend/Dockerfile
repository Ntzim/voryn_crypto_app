# syntax=docker/dockerfile:1.7
FROM node:24-alpine AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

FROM base AS deps
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# Local development (docker compose): source is bind-mounted, hot reload enabled.
FROM deps AS dev
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]

FROM deps AS build
COPY . .
RUN npm run build

# Production image: standalone server only, non-root. API_INTERNAL_URL is read at runtime.
FROM base AS runtime
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
RUN addgroup -S -g 10001 voryn && adduser -S -u 10001 -G voryn voryn
COPY --from=build --chown=voryn:voryn /app/.next/standalone ./
COPY --from=build --chown=voryn:voryn /app/.next/static ./.next/static
COPY --from=build --chown=voryn:voryn /app/public ./public
USER voryn
EXPOSE 3000
CMD ["node", "server.js"]
