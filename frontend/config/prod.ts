import type { UserConfigExport } from '@tarojs/cli'

export default {
  mini: {},
  h5: {
    publicPath: './',
  },
  env: {
    TARO_APP_API_URL: 'https://api.promiselink.cn'
  }
} satisfies UserConfigExport
