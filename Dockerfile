FROM node:18-slim

# Instala:
# 1. Dependências do Chrome e o próprio Chrome Stable (para Codecs H.264)
# 2. iproute2 (para ter o comando 'ip' e configurar rotas 5G)
# 3. procps (opcional, útil para debug com 'ps')
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    iproute2 \
    procps \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    --no-install-recommends \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/googlechrome-linux-keyring.gpg \
    && sh -c 'echo "deb [arch=amd64 signed-by=/usr/share/keyrings/googlechrome-linux-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list' \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala Puppeteer
RUN npm install puppeteer

# Copia o script do player (certifique-se que o dashjs_node_player.js local é o que tem o log de frames!)
COPY dashjs_node_player.js .

# Configura o Puppeteer para usar o Chrome instalado
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome-stable

CMD ["node", "dashjs_node_player.js"]