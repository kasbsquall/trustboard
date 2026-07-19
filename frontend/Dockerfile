# TrustBoard dashboard frontend (Next.js). Build from frontend/:
#   docker build -f frontend/Dockerfile -t trustboard-frontend ./frontend
# The public backend URL is baked in at build time; the browser needs it.
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# Cap Node's heap so a build does not exhaust the RAM of a shared host.
ENV NODE_OPTIONS=--max-old-space-size=768
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.js ./next.config.js

EXPOSE 3000
CMD ["npm", "run", "start"]
