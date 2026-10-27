import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.js'

// Unit tests mount views in happy-dom on recorded C6 responses; nothing reaches the network.
export default mergeConfig(viteConfig, defineConfig({
  test: {
    environment: 'happy-dom',
    include: ['tests/unit/**/*.spec.js'],
    env: { TZ: 'UTC' }
  }
}))
