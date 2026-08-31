<script setup>
import { onMounted, ref } from 'vue'
import { api } from './api'
import PlatformShell from './PlatformShell.vue'

const loading = ref(true)
const user = ref(null)
const error = ref('')
const submitting = ref(false)
const form = ref({ email: '', password: '' })

async function checkSession() {
  try {
    user.value = await api.me()
  } catch (err) {
    if (err.status !== 401) error.value = err.message
  } finally {
    loading.value = false
  }
}

async function login() {
  if (submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    user.value = await api.login(form.value.email.trim(), form.value.password)
    form.value.password = ''
  } catch (err) {
    error.value = err.message
  } finally {
    submitting.value = false
  }
}

async function logout() {
  try { await api.logout() } catch (_) {}
  user.value = null
}

onMounted(checkSession)
</script>

<template>
  <div v-if="loading" class="auth-loading">Loading WA Connect…</div>
  <main v-else-if="!user" class="login-page">
    <section class="login-card">
      <div class="login-brand">
        <div class="logo">WA</div>
        <div><strong>WA Connect</strong><span>Secure workspace access</span></div>
      </div>
      <p class="eyebrow">Welcome back</p>
      <h1>Sign in</h1>
      <p class="login-intro">Sign in to access your WA Connect workspace.</p>
      <form @submit.prevent="login">
        <label>Email address<input v-model="form.email" type="email" autocomplete="username" required autofocus /></label>
        <label>Password<input v-model="form.password" type="password" autocomplete="current-password" required /></label>
        <button class="primary login-button" :disabled="submitting">{{ submitting ? 'Signing in…' : 'Sign in' }}</button>
        <p v-if="error" class="form-error">{{ error }}</p>
      </form>
    </section>
  </main>
  <PlatformShell v-else :current-user="user" @logout="logout" />
</template>
