FROM node:18-slim

RUN apt-get update && apt-get install -y \
    wget \
        gnupg \
            ca-certificates \
                procps \
                    libnss3 \
                        libatk1.0-0 \
                            libatk-bridge2.0-0 \
                                libcups2 \
                                    libdrm2 \
                                        libxkbcommon0 \
                                            libxcomposite1 \
                                                libxdamage1 \
                                                    libxext6 \
                                                        libxfixes3 \
                                                            libxrandr2 \
                                                                libgbm1 \
                                                                    libpango-1.0-0 \
                                                                        libcairo2 \
                                                                            libasound2 \
                                                                                python3 \
                                                                                    python3-pip \
                                                                                        && rm -rf /var/lib/apt/lists/*

                                                                                        RUN apt-get update && apt-get install -y chromium

                                                                                        ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
                                                                                        ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

                                                                                        WORKDIR /app

                                                                                        COPY package*.json ./
                                                                                        RUN npm install

                                                                                        COPY . .

                                                                                        RUN pip3 install pandas

                                                                                        EXPOSE 7860

                                                                                        CMD ["node", "server.js"]
                                                                                        