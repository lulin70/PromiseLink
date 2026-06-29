import { defineConfig } from '@tarojs/cli'
import devConfig from './dev'
import prodConfig from './prod'

export default defineConfig(async () => {
  return {
    ...(process.env.NODE_ENV === 'production' ? prodConfig : devConfig),
    projectName: 'promiselink-frontend',
    date: '2026-6-12',
    designWidth: 750,
    deviceRatio: {
      640: 2.34 / 2,
      750: 1,
      375: 2,
      828: 1.81 / 2,
    },
    sourceRoot: 'src',
    outputRoot: 'dist',
    plugins: [],
    defineConstants: {},
    copy: {
      patterns: [
        { from: 'src/icons/', to: 'dist/static/icons/' },
      ],
      options: {},
    },
    framework: 'react',
    compiler: {
      type: 'webpack5',
      prebundle: { enable: false },
    },
    cache: {
      enable: false,
    },
    h5: {
      publicPath: '/',
      staticDirectory: 'static',
      devServer: {
        port: 3000,
        proxy: {
          '/api': {
            target: 'http://localhost:8000',
            changeOrigin: true,
          },
        },
      },
      router: {
        mode: 'browser',
      },
      esnextModules: [],
    },
  }
})
