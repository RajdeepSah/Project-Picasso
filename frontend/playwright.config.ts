import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:8765',
    viewport: { width: 1440, height: 1050 },
    launchOptions: process.env.PICASSO_BROWSER_PATH ? { executablePath: process.env.PICASSO_BROWSER_PATH } : {},
  },
  webServer: {
    command: 'python3 ../scripts/picasso.py --no-browser --port 8765',
    url: 'http://127.0.0.1:8765/api/health',
    reuseExistingServer: false,
    timeout: 30000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10000 },
  },
});
