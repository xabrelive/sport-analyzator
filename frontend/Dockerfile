FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY . .
# Прокси /api на бэкенд: при сборке передать BACKEND_URL (для rewrites в next.config)
ARG BACKEND_URL=http://backend:11001
ENV BACKEND_URL=$BACKEND_URL
RUN npm run build
EXPOSE 11000
CMD ["npm", "run", "start", "--", "-p", "11000", "-H", "0.0.0.0"]
