import { reactive } from 'vue'

export const session = reactive({
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  login(user) {
    this.user = user
    localStorage.setItem('user', JSON.stringify(user))
  },
  logout() {
    this.user = null
    localStorage.removeItem('user')
  },
  get isBuyer() { return this.user && ['buyer', 'admin'].includes(this.user.role) },
  get isChecker() { return this.user && ['checker', 'admin'].includes(this.user.role) },
})
