import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

api.interceptors.request.use((config) => {
  const user = JSON.parse(localStorage.getItem('user') || 'null')
  if (user) config.headers['X-User-Id'] = user.id
  return config
})

api.interceptors.response.use(
  (resp) => resp,
  (err) => {
    const detail = err.response?.data?.detail
    let msg = err.message
    if (typeof detail === 'string') msg = detail
    else if (detail?.detail) msg = detail.detail + (detail.reasons ? '：' + detail.reasons.join('；') : '')
    else if (Array.isArray(detail)) msg = detail.map((d) => d.msg).join('；')
    err.friendlyMessage = msg
    return Promise.reject(err)
  }
)

export default api
