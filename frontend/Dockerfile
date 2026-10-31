# syntax=docker/dockerfile:1.7
FROM node:24-alpine AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

FROM base AS deps
COPY package.json package-lock.json ./
RUN npm ci && npm cache clean --force

# Local development (docker compose): source is bind-mounted, hot reload enabled.
FROM deps AS dev
COPY . .
EXPOSE 3000
# Root on purpose: the bind-mounted source keeps the host's file owner. Never deployed;
# the runtime stage below runs as an unprivileged user.
# nosemgrep: dockerfile.security.missing-user.missing-user
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]

FROM deps AS build
COPY . .
RUN npm run build

# Production image: standalone server only, non-root. API_INTERNAL_URL is read at runtime.
FROM base AS runtime
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
# The standalone server only needs `node`. npm, corepack and yarn are build tools that ship
# their own dependency trees (Trivy flagged HIGH advisories in npm's bundled undici and
# brace-expansion), so they are removed from the image that runs in production.
RUN addgroup -S -g 10001 voryn && adduser -S -u 10001 -G voryn voryn \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack /opt/yarn-* \
              /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack /usr/local/bin/yarn /usr/local/bin/yarnpkg
COPY --from=build --chown=voryn:voryn /app/.next/standalone ./
COPY --from=build --chown=voryn:voryn /app/.next/static ./.next/static
COPY --from=build --chown=voryn:voryn /app/public ./public
USER voryn
EXPOSE 3000
CMD ["node", "server.js"]
