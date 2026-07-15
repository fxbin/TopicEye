FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# `rewrites` is resolved during `next build`.  Keep the container service
# address available at build time as well as at runtime, otherwise a
# production image falls back to the host-only development API URL.
ARG BACKEND_API_URL=http://backend:8000
ENV BACKEND_API_URL=${BACKEND_API_URL}
RUN npm run build

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD node -e "const r=require('http').get('http://127.0.0.1:3000/api/health',x=>{x.resume();process.exit(x.statusCode===200?0:1)});r.setTimeout(3000,()=>{r.destroy();process.exit(1)});r.on('error',()=>process.exit(1))" || exit 1

CMD ["npm", "run", "start"]
