export const buildBindDeepLink = (bindCode: string, botUsername?: string): string => {
  const username = (botUsername || '').trim().replace(/^@+/, '')
  const code = (bindCode || '').trim()
  if (!username || !code) return ''
  return `https://t.me/${username}?start=bind_${encodeURIComponent(code)}`
}

