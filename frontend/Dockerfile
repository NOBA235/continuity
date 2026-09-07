# Continuity.Agent -- Next.js dashboard
FROM node:22-slim AS deps
WORKDIR /srv
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-slim AS build
WORKDIR /srv
COPY --from=deps /srv/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* vars are baked in at build time, not read at container start.
ARG NEXT_PUBLIC_API_URL=http://localhost:8080
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /srv
ENV NODE_ENV=production
COPY --from=build /srv/public ./public
COPY --from=build /srv/.next ./.next
COPY --from=build /srv/node_modules ./node_modules
COPY --from=build /srv/package.json ./package.json

EXPOSE 3000
CMD ["sh", "-c", "npm run start -- --port ${PORT:-3000}"]
