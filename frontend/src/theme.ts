import type { ThemeConfig } from 'antd'

/**
 * Shared visual language for the application shell and feature pages.
 * Keep feature-specific colors semantic (for example workflow node types),
 * but route all primary actions and feedback through these tokens.
 */
export const appColors = {
  primary: '#1B7F8C',
  primaryHover: '#2A97A4',
  primaryStrong: '#126B78',
  primarySoft: '#E3F5F5',
  infoSoft: '#E8F2F4',
  success: '#18815A',
  successSoft: '#E8F6EF',
  warning: '#C27A17',
  warningSoft: '#FFF4DE',
  danger: '#C53D4B',
  dangerSoft: '#FDECEE',
  text: '#172B3A',
  textSecondary: '#617487',
  textMuted: '#8FA1AF',
  surface: '#F4F7F9',
  surfaceStrong: '#FFFFFF',
  border: '#D8E3E8',
  nav: '#0B1826',
  navText: '#9BB0C0',
  navActive: '#73E0DF',
} as const

export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: appColors.primary,
    colorInfo: appColors.primary,
    colorLink: appColors.primaryStrong,
    colorSuccess: appColors.success,
    colorWarning: appColors.warning,
    colorError: appColors.danger,
    colorText: appColors.text,
    colorTextSecondary: appColors.textSecondary,
    colorTextTertiary: appColors.textMuted,
    colorBgLayout: appColors.surface,
    colorBgContainer: appColors.surfaceStrong,
    colorBorder: appColors.border,
    colorBorderSecondary: '#E7EEF1',
    borderRadius: 10,
    borderRadiusLG: 14,
    controlHeight: 36,
    controlHeightSM: 30,
    fontFamily:
      'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif',
  },
  components: {
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      dangerShadow: 'none',
      defaultColor: appColors.text,
      defaultBg: appColors.surfaceStrong,
      defaultBorderColor: appColors.border,
      defaultHoverColor: appColors.primaryStrong,
      defaultHoverBorderColor: appColors.primary,
      defaultHoverBg: appColors.primarySoft,
    },
    Card: {
      borderRadiusLG: 14,
    },
    Input: {
      activeBorderColor: appColors.primary,
      hoverBorderColor: appColors.primaryHover,
      activeShadow: '0 0 0 2px rgba(27, 127, 140, 0.12)',
    },
    Layout: {
      bodyBg: appColors.surface,
      headerBg: appColors.surfaceStrong,
      siderBg: appColors.nav,
    },
    Menu: {
      darkItemBg: appColors.nav,
      darkSubMenuItemBg: appColors.nav,
      darkItemSelectedBg: 'rgba(48, 169, 181, 0.18)',
      darkItemSelectedColor: '#F1FFFF',
    },
    Select: {
      activeBorderColor: appColors.primary,
      hoverBorderColor: appColors.primaryHover,
      activeOutlineColor: 'rgba(27, 127, 140, 0.12)',
    },
  },
}
