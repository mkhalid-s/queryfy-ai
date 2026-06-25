/**
 * AppHeader Component Tests
 *
 * Tests the application header including:
 * - Logo and branding
 * - Sidebar toggle
 * - Theme toggle
 * - Connection status indicator
 * - Settings and Context Studio buttons
 * - Event emissions
 */

import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AppHeader from '../AppHeader.vue'

// Mock lucide-vue-next icons
vi.mock('lucide-vue-next', () => ({
  Sun: { template: '<span class="icon-sun">☀️</span>' },
  Moon: { template: '<span class="icon-moon">🌙</span>' },
  Settings: { template: '<span class="icon-settings">⚙️</span>' },
  Menu: { template: '<span class="icon-menu">☰</span>' },
  Database: { template: '<span class="icon-database">🗄️</span>' }
}))

describe('AppHeader', () => {
  const createWrapper = (props = {}) => {
    return mount(AppHeader, {
      props: {
        isDark: false,
        hasSession: false,
        ...props
      }
    })
  }

  // ============================================
  // RENDERING TESTS
  // ============================================

  describe('Rendering', () => {
    it('renders the header', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.app-header').exists()).toBe(true)
    })

    it('renders brand name', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.brand-name').text()).toBe('QueryfyAI')
    })

    it('renders logo SVG', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.logo svg').exists()).toBe(true)
    })

    it('renders sidebar toggle button', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.sidebar-toggle').exists()).toBe(true)
    })

    it('renders theme toggle button', () => {
      const wrapper = createWrapper()
      const themeBtn = wrapper.findAll('.icon-btn').find(btn =>
        btn.attributes('title')?.includes('Mode')
      )
      expect(themeBtn.exists()).toBe(true)
    })

    it('renders settings button', () => {
      const wrapper = createWrapper()
      const settingsBtn = wrapper.findAll('.icon-btn').find(btn =>
        btn.attributes('title') === 'Settings'
      )
      expect(settingsBtn.exists()).toBe(true)
    })
  })

  // ============================================
  // CONNECTION STATUS TESTS
  // ============================================

  describe('Connection Status', () => {
    it('shows disconnected status when no session', () => {
      const wrapper = createWrapper({ hasSession: false })
      const status = wrapper.find('.status-indicator')

      expect(status.classes()).toContain('disconnected')
      expect(status.text()).toContain('Not connected')
    })

    it('shows connected status when has session', () => {
      const wrapper = createWrapper({ hasSession: true })
      const status = wrapper.find('.status-indicator')

      expect(status.classes()).toContain('connected')
      expect(status.text()).toContain('Connected')
    })

    it('renders status dot', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.status-dot').exists()).toBe(true)
    })
  })

  // ============================================
  // THEME TOGGLE TESTS
  // ============================================

  describe('Theme Toggle', () => {
    it('shows moon icon in light mode', () => {
      const wrapper = createWrapper({ isDark: false })
      expect(wrapper.find('.icon-moon').exists()).toBe(true)
      expect(wrapper.find('.icon-sun').exists()).toBe(false)
    })

    it('shows sun icon in dark mode', () => {
      const wrapper = createWrapper({ isDark: true })
      expect(wrapper.find('.icon-sun').exists()).toBe(true)
      expect(wrapper.find('.icon-moon').exists()).toBe(false)
    })

    it('has correct title in light mode', () => {
      const wrapper = createWrapper({ isDark: false })
      const themeBtn = wrapper.findAll('.icon-btn').find(btn =>
        btn.attributes('title')?.includes('Dark Mode')
      )
      expect(themeBtn.attributes('title')).toBe('Switch to Dark Mode')
    })

    it('has correct title in dark mode', () => {
      const wrapper = createWrapper({ isDark: true })
      const themeBtn = wrapper.findAll('.icon-btn').find(btn =>
        btn.attributes('title')?.includes('Light Mode')
      )
      expect(themeBtn.attributes('title')).toBe('Switch to Light Mode')
    })
  })

  // ============================================
  // DATA STUDIO BUTTON TESTS
  // ============================================

  describe('Context Studio Button', () => {
    it('shows Context Studio button when connected', () => {
      const wrapper = createWrapper({ hasSession: true })
      const dataStudioBtn = wrapper.findAll('.icon-btn').find(btn =>
        btn.attributes('title') === 'Context Studio'
      )
      expect(dataStudioBtn.exists()).toBe(true)
    })

    it('hides Context Studio button when not connected', () => {
      const wrapper = createWrapper({ hasSession: false })
      const dataStudioBtn = wrapper.findAll('.icon-btn').find(btn =>
        btn.attributes('title') === 'Context Studio'
      )
      expect(dataStudioBtn).toBeUndefined()
    })
  })

  // ============================================
  // EVENT EMISSION TESTS
  // ============================================

  describe('Event Emissions', () => {
    it('emits toggle-sidebar when sidebar button clicked', async () => {
      const wrapper = createWrapper()
      await wrapper.find('.sidebar-toggle').trigger('click')

      expect(wrapper.emitted('toggle-sidebar')).toBeTruthy()
    })

    it('emits toggle-theme when theme button clicked', async () => {
      const wrapper = createWrapper()
      const themeBtn = wrapper.findAll('.icon-btn').find(btn =>
        btn.attributes('title')?.includes('Mode')
      )
      await themeBtn.trigger('click')

      expect(wrapper.emitted('toggle-theme')).toBeTruthy()
    })

    it('emits open-settings when settings button clicked', async () => {
      const wrapper = createWrapper()
      const settingsBtn = wrapper.findAll('.icon-btn').find(btn =>
        btn.attributes('title') === 'Settings'
      )
      await settingsBtn.trigger('click')

      expect(wrapper.emitted('open-settings')).toBeTruthy()
    })

    it('emits open-context-studio when context studio button clicked', async () => {
      const wrapper = createWrapper({ hasSession: true })
      const dataStudioBtn = wrapper.findAll('.icon-btn').find(btn =>
        btn.attributes('title') === 'Context Studio'
      )
      await dataStudioBtn.trigger('click')

      expect(wrapper.emitted('open-context-studio')).toBeTruthy()
    })
  })

  // ============================================
  // BUTTON TITLES TESTS
  // ============================================

  describe('Button Titles', () => {
    it('sidebar toggle has correct title', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.sidebar-toggle').attributes('title')).toBe('Toggle History')
    })

    it('settings button has correct title', () => {
      const wrapper = createWrapper()
      const settingsBtn = wrapper.findAll('.icon-btn').find(btn =>
        btn.attributes('title') === 'Settings'
      )
      expect(settingsBtn.attributes('title')).toBe('Settings')
    })
  })

  // ============================================
  // STRUCTURE TESTS
  // ============================================

  describe('Structure', () => {
    it('has left section with brand', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.header-left').exists()).toBe(true)
      expect(wrapper.find('.header-brand').exists()).toBe(true)
    })

    it('has right section with actions', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.header-actions').exists()).toBe(true)
    })
  })
})
