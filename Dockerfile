FROM python:3.10-slim

# Install Node.js 20.x and system deps for Chromium
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Playwright browser path
ENV PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright

WORKDIR /app

# Copy package files first for better caching
COPY package*.json ./
RUN npm install

# Install Python dependencies
RUN pip install --no-cache-dir pandas openpyxl playwright playwright-stealth

# Install Playwright Chromium + system deps
RUN playwright install-deps chromium \
    && playwright install chromium

# Copy all app files
COPY . .

# Create uploads directory
RUN mkdir -p uploads

# Hugging Face runs as user 1000
RUN useradd -m -u 1000 user \
    && chown -R user:user /app

USER user

ENV PORT=7860
EXPOSE 7860

CMD ["npm", "start"]