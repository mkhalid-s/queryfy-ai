/**
 * QueryBar Component Tests
 *
 * Tests the unified floating input bar including:
 * - Mode toggles (Standard/Analyst)
 * - Text input with send/stop
 * - Conversation controls
 * - Keyboard shortcuts
 * - Exposed methods
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import QueryBar from '../QueryBar.vue'

// Mock lucide-vue-next icons
vi.mock('lucide-vue-next', () => ({
  Zap: { template: '<span class="icon-zap">⚡</span>' },
  BrainCircuit: { template: '<span class="icon-brain">🧠</span>' },
  ArrowUp: { template: '<span class="icon-arrow">↑</span>' },
  Square: { template: '<span class="icon-square">⬜</span>' },
  MessageSquarePlus: { template: '<span class="icon-msg">💬</span>' },
  RefreshCw: { template: '<span class="icon-refresh">🔄</span>' }
}))

// Mock composables
const mockSetResponseMode = vi.fn()
const mockIsAnalystMode = { value: false }

vi.mock('../../../composables/useQueryOptions', () => ({
  useQueryOptions: () => ({
    isAnalystMode: mockIsAnalystMode,
    setResponseMode: mockSetResponseMode
  })
}))

describe('QueryBar', () => {
  let wrapper

  const createWrapper = (props = {}) => {
    setActivePinia(createPinia())
    return mount(QueryBar, {
      props: {
        disabled: false,
        isGenerating: false,
        placeholder: 'Ask about your data...',
        ...props
      }
    })
  }

  beforeEach(() => {
    vi.clearAllMocks()
    mockIsAnalystMode.value = false
    wrapper = createWrapper()
  })

  // ============================================
  // RENDERING TESTS
  // ============================================

  describe('Rendering', () => {
    it('renders the query bar container', () => {
      expect(wrapper.find('.query-bar-wrapper').exists()).toBe(true)
      expect(wrapper.find('.query-bar').exists()).toBe(true)
    })

    it('renders textarea with placeholder', () => {
      const textarea = wrapper.find('textarea')
      expect(textarea.exists()).toBe(true)
      expect(textarea.attributes('placeholder')).toBe('Ask about your data...')
    })

    it('renders mode indicator button', () => {
      expect(wrapper.find('.mode-indicator').exists()).toBe(true)
    })

    it('renders send button when not generating', () => {
      expect(wrapper.find('.action-btn.send').exists()).toBe(true)
      expect(wrapper.find('.action-btn.stop').exists()).toBe(false)
    })

    it('renders stop button when generating', () => {
      wrapper = createWrapper({ isGenerating: true })
      expect(wrapper.find('.action-btn.stop').exists()).toBe(true)
      expect(wrapper.find('.action-btn.send').exists()).toBe(false)
    })

    it('renders mode pills', () => {
      const pills = wrapper.findAll('.mode-pills .pill')
      expect(pills.length).toBe(2)
      expect(pills[0].text()).toContain('Standard')
      expect(pills[1].text()).toContain('Analyst')
    })

    it('uses custom placeholder', () => {
      wrapper = createWrapper({ placeholder: 'Custom placeholder' })
      expect(wrapper.find('textarea').attributes('placeholder')).toBe('Custom placeholder')
    })
  })

  // ============================================
  // INPUT HANDLING TESTS
  // ============================================

  describe('Input Handling', () => {
    it('updates textarea value on input', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('SELECT * FROM users')

      expect(textarea.element.value).toBe('SELECT * FROM users')
    })

    it('disables textarea when disabled prop is true', () => {
      wrapper = createWrapper({ disabled: true })
      expect(wrapper.find('textarea').attributes('disabled')).toBeDefined()
    })

    it('has aria-label for accessibility', () => {
      expect(wrapper.find('textarea').attributes('aria-label')).toBe('Enter your natural language query')
    })
  })

  // ============================================
  // SUBMIT TESTS
  // ============================================

  describe('Submit Functionality', () => {
    it('emits submit event on button click', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('Test query')

      await wrapper.find('.action-btn.send').trigger('click')

      expect(wrapper.emitted('submit')).toBeTruthy()
      expect(wrapper.emitted('submit')[0]).toEqual(['Test query'])
    })

    it('clears input after submit', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('Test query')

      await wrapper.find('.action-btn.send').trigger('click')

      expect(textarea.element.value).toBe('')
    })

    it('trims whitespace from query', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('  Test query  ')

      await wrapper.find('.action-btn.send').trigger('click')

      expect(wrapper.emitted('submit')[0]).toEqual(['Test query'])
    })

    it('does not submit empty query', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('   ')

      await wrapper.find('.action-btn.send').trigger('click')

      expect(wrapper.emitted('submit')).toBeFalsy()
    })

    it('disables send button when query is empty', () => {
      const sendBtn = wrapper.find('.action-btn.send')
      expect(sendBtn.attributes('disabled')).toBeDefined()
    })

    it('enables send button when query has content', async () => {
      await wrapper.find('textarea').setValue('Test')
      await nextTick()

      const sendBtn = wrapper.find('.action-btn.send')
      expect(sendBtn.attributes('disabled')).toBeUndefined()
    })

    it('does not submit when disabled', async () => {
      wrapper = createWrapper({ disabled: true })
      await wrapper.find('textarea').setValue('Test')

      // Send button should be disabled
      expect(wrapper.find('.action-btn.send').attributes('disabled')).toBeDefined()
    })
  })

  // ============================================
  // KEYBOARD SHORTCUT TESTS
  // ============================================

  describe('Keyboard Shortcuts', () => {
    it('submits on Ctrl+Enter', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('Test query')

      await textarea.trigger('keydown', {
        key: 'Enter',
        ctrlKey: true
      })

      expect(wrapper.emitted('submit')).toBeTruthy()
    })

    it('submits on Cmd+Enter (Mac)', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('Test query')

      await textarea.trigger('keydown', {
        key: 'Enter',
        metaKey: true
      })

      expect(wrapper.emitted('submit')).toBeTruthy()
    })

    it('submits on plain Enter (without shift)', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('Test query')

      await textarea.trigger('keydown', {
        key: 'Enter',
        shiftKey: false
      })

      expect(wrapper.emitted('submit')).toBeTruthy()
    })

    it('does not submit on Shift+Enter (allows newline)', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('Test query')

      await textarea.trigger('keydown', {
        key: 'Enter',
        shiftKey: true
      })

      expect(wrapper.emitted('submit')).toBeFalsy()
    })
  })

  // ============================================
  // STOP FUNCTIONALITY TESTS
  // ============================================

  describe('Stop Functionality', () => {
    it('emits stop event when stop button clicked', async () => {
      wrapper = createWrapper({ isGenerating: true })

      await wrapper.find('.action-btn.stop').trigger('click')

      expect(wrapper.emitted('stop')).toBeTruthy()
    })

    it('stop button has correct title', () => {
      wrapper = createWrapper({ isGenerating: true })
      expect(wrapper.find('.action-btn.stop').attributes('title')).toBe('Stop generation')
    })
  })

  // ============================================
  // MODE TOGGLE TESTS
  // ============================================

  describe('Mode Toggle', () => {
    it('calls setResponseMode when Standard pill clicked', async () => {
      const pills = wrapper.findAll('.mode-pills .pill')
      await pills[0].trigger('click')

      expect(mockSetResponseMode).toHaveBeenCalledWith('standard')
    })

    it('calls setResponseMode when Analyst pill clicked', async () => {
      const pills = wrapper.findAll('.mode-pills .pill')
      await pills[1].trigger('click')

      expect(mockSetResponseMode).toHaveBeenCalledWith('analyst')
    })

    it('toggles mode on mode indicator click', async () => {
      mockIsAnalystMode.value = false
      await wrapper.find('.mode-indicator').trigger('click')

      expect(mockSetResponseMode).toHaveBeenCalledWith('analyst')
    })

    it('toggles from analyst to standard', async () => {
      mockIsAnalystMode.value = true
      wrapper = createWrapper()
      await wrapper.find('.mode-indicator').trigger('click')

      expect(mockSetResponseMode).toHaveBeenCalledWith('standard')
    })

    it('shows correct icon for current mode', () => {
      // Check that mode indicator exists and has an icon
      const modeIndicator = wrapper.find('.mode-indicator')
      expect(modeIndicator.exists()).toBe(true)
      // The icon should exist (either zap or brain)
      expect(modeIndicator.find('span[class^="icon-"]').exists()).toBe(true)
    })
  })

  // ============================================
  // EXPOSED METHODS TESTS
  // ============================================

  describe('Exposed Methods', () => {
    it('exposes focus method', () => {
      expect(typeof wrapper.vm.focus).toBe('function')
    })

    it('exposes setQuery method', () => {
      expect(typeof wrapper.vm.setQuery).toBe('function')
    })

    it('setQuery updates textarea value', async () => {
      wrapper.vm.setQuery('Prefilled query')
      await nextTick()

      expect(wrapper.find('textarea').element.value).toBe('Prefilled query')
    })
  })

  // ============================================
  // SEND BUTTON TITLE TESTS
  // ============================================

  describe('Button Titles', () => {
    it('send button has keyboard shortcut hint', () => {
      expect(wrapper.find('.action-btn.send').attributes('title')).toBe('Send (Ctrl+Enter)')
    })

    it('mode indicator shows current mode in title', () => {
      const title = wrapper.find('.mode-indicator').attributes('title')
      // Title should contain mode information and click action
      expect(title).toContain('Mode')
      expect(title).toContain('Click')
    })
  })
})
