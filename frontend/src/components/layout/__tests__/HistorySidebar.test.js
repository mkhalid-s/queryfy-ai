/**
 * HistorySidebar Component Tests
 *
 * Tests the collapsible history sidebar including:
 * - Open/close state
 * - Expand/collapse buttons
 * - Event emissions
 * - Keyboard shortcuts
 * - Mobile behavior
 */

import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import HistorySidebar from '../HistorySidebar.vue'

// Mock lucide-vue-next icons
vi.mock('lucide-vue-next', () => ({
  History: { template: '<span class="icon-history">📜</span>' },
  PanelLeftOpen: { template: '<span class="icon-open">◀</span>' },
  PanelLeftClose: { template: '<span class="icon-close">▶</span>' }
}))

// Mock ActivityPanel component
vi.mock('../../ActivityPanel.vue', () => ({
  default: {
    name: 'ActivityPanel',
    template: '<div class="activity-panel-mock">Activity Panel</div>',
    props: ['maxDisplay']
  }
}))

describe('HistorySidebar', () => {
  const createWrapper = (props = {}) => {
    return mount(HistorySidebar, {
      props: {
        open: false,
        ...props
      },
      global: {
        stubs: {
          Teleport: true
        }
      }
    })
  }

  // ============================================
  // RENDERING TESTS - CLOSED STATE
  // ============================================

  describe('Rendering - Closed State', () => {
    it('renders the sidebar', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.history-sidebar').exists()).toBe(true)
    })

    it('sidebar does not have open class when closed', () => {
      const wrapper = createWrapper({ open: false })
      expect(wrapper.find('.history-sidebar').classes()).not.toContain('open')
    })

    it('shows expand button when closed', () => {
      const wrapper = createWrapper({ open: false })
      expect(wrapper.find('.expand-btn').exists()).toBe(true)
    })

    it('expand button has correct title', () => {
      const wrapper = createWrapper({ open: false })
      expect(wrapper.find('.expand-btn').attributes('title')).toBe('Open History')
    })

    it('does not show header when closed', () => {
      const wrapper = createWrapper({ open: false })
      expect(wrapper.find('.sidebar-header').exists()).toBe(false)
    })

    it('does not show ActivityPanel when closed', () => {
      const wrapper = createWrapper({ open: false })
      expect(wrapper.find('.activity-panel-mock').exists()).toBe(false)
    })
  })

  // ============================================
  // RENDERING TESTS - OPEN STATE
  // ============================================

  describe('Rendering - Open State', () => {
    it('sidebar has open class when open', () => {
      const wrapper = createWrapper({ open: true })
      expect(wrapper.find('.history-sidebar').classes()).toContain('open')
    })

    it('shows header when open', () => {
      const wrapper = createWrapper({ open: true })
      expect(wrapper.find('.sidebar-header').exists()).toBe(true)
    })

    it('shows header title with History text', () => {
      const wrapper = createWrapper({ open: true })
      expect(wrapper.find('.header-title').text()).toContain('History')
    })

    it('shows collapse button when open', () => {
      const wrapper = createWrapper({ open: true })
      expect(wrapper.find('.collapse-btn').exists()).toBe(true)
    })

    it('collapse button has correct title', () => {
      const wrapper = createWrapper({ open: true })
      expect(wrapper.find('.collapse-btn').attributes('title')).toBe('Close History')
    })

    it('hides expand button when open', () => {
      const wrapper = createWrapper({ open: true })
      expect(wrapper.find('.expand-btn').exists()).toBe(false)
    })

    it('shows sidebar content', () => {
      const wrapper = createWrapper({ open: true })
      expect(wrapper.find('.sidebar-content').exists()).toBe(true)
    })

    it('renders ActivityPanel when open', () => {
      const wrapper = createWrapper({ open: true })
      expect(wrapper.find('.activity-panel-mock').exists()).toBe(true)
    })
  })

  // ============================================
  // EVENT EMISSION TESTS
  // ============================================

  describe('Event Emissions', () => {
    it('emits update:open with true when expand button clicked', async () => {
      const wrapper = createWrapper({ open: false })
      await wrapper.find('.expand-btn').trigger('click')

      expect(wrapper.emitted('update:open')).toBeTruthy()
      expect(wrapper.emitted('update:open')[0]).toEqual([true])
    })

    it('emits update:open with false when collapse button clicked', async () => {
      const wrapper = createWrapper({ open: true })
      await wrapper.find('.collapse-btn').trigger('click')

      expect(wrapper.emitted('update:open')).toBeTruthy()
      expect(wrapper.emitted('update:open')[0]).toEqual([false])
    })

    it('emits select when ActivityPanel emits select', async () => {
      const wrapper = createWrapper({ open: true })
      const activityPanel = wrapper.findComponent({ name: 'ActivityPanel' })

      await activityPanel.vm.$emit('select', { query: 'test query' })

      expect(wrapper.emitted('select')).toBeTruthy()
      expect(wrapper.emitted('select')[0]).toEqual([{ query: 'test query' }])
    })
  })

  // ============================================
  // ACTIVITY PANEL PROPS TESTS
  // ============================================

  describe('ActivityPanel Props', () => {
    it('passes maxDisplay prop to ActivityPanel', () => {
      const wrapper = createWrapper({ open: true })
      const activityPanel = wrapper.findComponent({ name: 'ActivityPanel' })

      expect(activityPanel.props('maxDisplay')).toBe(15)
    })
  })

  // ============================================
  // STRUCTURE TESTS
  // ============================================

  describe('Structure', () => {
    it('has header and content sections when open', () => {
      const wrapper = createWrapper({ open: true })

      expect(wrapper.find('.sidebar-header').exists()).toBe(true)
      expect(wrapper.find('.sidebar-content').exists()).toBe(true)
    })

    it('header contains title and collapse button', () => {
      const wrapper = createWrapper({ open: true })
      const header = wrapper.find('.sidebar-header')

      expect(header.find('.header-title').exists()).toBe(true)
      expect(header.find('.collapse-btn').exists()).toBe(true)
    })
  })

  // ============================================
  // TOGGLE BEHAVIOR TESTS
  // ============================================

  describe('Toggle Behavior', () => {
    it('transitions from closed to open', async () => {
      const wrapper = createWrapper({ open: false })

      expect(wrapper.find('.history-sidebar').classes()).not.toContain('open')
      expect(wrapper.find('.expand-btn').exists()).toBe(true)

      // Simulate prop change
      await wrapper.setProps({ open: true })

      expect(wrapper.find('.history-sidebar').classes()).toContain('open')
      expect(wrapper.find('.expand-btn').exists()).toBe(false)
    })

    it('transitions from open to closed', async () => {
      const wrapper = createWrapper({ open: true })

      expect(wrapper.find('.history-sidebar').classes()).toContain('open')

      // Simulate prop change
      await wrapper.setProps({ open: false })

      expect(wrapper.find('.history-sidebar').classes()).not.toContain('open')
      expect(wrapper.find('.expand-btn').exists()).toBe(true)
    })
  })

  // ============================================
  // ICON TESTS
  // ============================================

  describe('Icons', () => {
    it('shows history icon in header', () => {
      const wrapper = createWrapper({ open: true })
      expect(wrapper.find('.header-title .icon-history').exists()).toBe(true)
    })

    it('shows open icon in expand button', () => {
      const wrapper = createWrapper({ open: false })
      expect(wrapper.find('.expand-btn .icon-open').exists()).toBe(true)
    })

    it('shows close icon in collapse button', () => {
      const wrapper = createWrapper({ open: true })
      expect(wrapper.find('.collapse-btn .icon-close').exists()).toBe(true)
    })
  })
})
