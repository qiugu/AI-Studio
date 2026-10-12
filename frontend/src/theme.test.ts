import { describe, expect, it } from 'vitest'
import { appColors, appTheme } from './theme'

describe('AI Studio theme', () => {
  it('uses intelligent teal as the shared primary color', () => {
    expect(appColors.primary).toBe('#1B7F8C')
    expect(appTheme.token?.colorPrimary).toBe(appColors.primary)
    expect(appTheme.token?.colorInfo).toBe(appColors.primary)
    expect(appTheme.token?.colorLink).toBe(appColors.primaryStrong)
  })

  it('keeps semantic feedback colors distinct from primary actions', () => {
    expect(appTheme.token?.colorSuccess).toBe(appColors.success)
    expect(appTheme.token?.colorWarning).toBe(appColors.warning)
    expect(appTheme.token?.colorError).toBe(appColors.danger)
    expect(appColors.warning).not.toBe(appColors.primary)
    expect(appColors.danger).not.toBe(appColors.primary)
  })
})
