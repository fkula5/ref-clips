const preferenceKey = 'ref-clips-theme'

export function getThemePreference(): boolean | 'auto' {
  try {
    const value = window.localStorage.getItem(preferenceKey)
    if (value === 'dark') return true
    if (value === 'light') return false
  } catch {
    // Storage can be blocked by the browser.
  }
  return 'auto'
}

export function saveThemePreference(dark: boolean) {
  try {
    window.localStorage.setItem(preferenceKey, dark ? 'dark' : 'light')
  } catch {
    // The change still applies for the current page.
  }
}
