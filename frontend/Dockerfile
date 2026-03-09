FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --legacy-peer-deps
COPY . .
RUN npm run build
EXPOSE 11000
CMD ["npm", "run", "start", "--", "-p", "11000", "-H", "0.0.0.0"]
