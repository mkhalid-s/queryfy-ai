/**
 * QueryInput Component Tests
 *
 * Tests the main query input component including:
 * - Basic rendering and props
 * - User input handling
 * - Submit functionality
 * - Keyboard shortcuts
 * - Stop generation functionality
 * - Disabled state
 * - Exposed methods
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import QueryInput from '../QueryInput.vue'

// Mock lucide-vue-next icons
vi.mock('lucide-vue-next', () => ({
  Send: { template: '<span class="icon-send">Send</span>' },
  Square: { template: '<span class="icon-square">Square</span>' }
}))

// Mock InputOptions component
vi.mock('../InputOptions.vue', () => ({
  default: { template: '<div class="input-options-mock">Options</div>' }
}))

describe('QueryInput', () => {
  let wrapper

  const createWrapper = (props = {}) => {
    return mount(QueryInput, {
      props: {
        placeholder: 'Ask about your data...',
        disabled: false,
        isGenerating: false,
        showOptions: true,
        ...props
      },
      global: {
        stubs: {
          InputOptions: true
        }
      }
    })
  }

  beforeEach(() => {
    wrapper = createWrapper()
  })

  // ============================================
  // RENDERING TESTS
  // ============================================

  describe('Rendering', () => {
    it('renders the query input container', () => {
      expect(wrapper.find('.query-input-container').exists()).toBe(true)
    })

    it('renders textarea with correct placeholder', () => {
      const textarea = wrapper.find('textarea')
      expect(textarea.exists()).toBe(true)
      expect(textarea.attributes('placeholder')).toBe('Ask about your data...')
    })

    it('renders send button when not generating', () => {
      expect(wrapper.find('.send-btn').exists()).toBe(true)
      expect(wrapper.find('.stop-btn').exists()).toBe(false)
    })

    it('renders stop button when generating', async () => {
      wrapper = createWrapper({ isGenerating: true })
      expect(wrapper.find('.stop-btn').exists()).toBe(true)
      expect(wrapper.find('.send-btn').exists()).toBe(false)
    })

    it('renders input options when showOptions is true', () => {
      expect(wrapper.findComponent({ name: 'InputOptions' }).exists()).toBe(true)
    })

    it('hides input options when showOptions is false', () => {
      wrapper = createWrapper({ showOptions: false })
      expect(wrapper.findComponent({ name: 'InputOptions' }).exists()).toBe(false)
    })

    it('shows keyboard hint when not disabled', () => {
      const hint = wrapper.find('.input-hint')
      expect(hint.text()).toContain('Ctrl')
      expect(hint.text()).toContain('Enter')
    })

    it('shows warning hint when disabled', () => {
      wrapper = createWrapper({ disabled: true })
      const hint = wrapper.find('.hint-warning')
      expect(hint.exists()).toBe(true)
      expect(hint.text()).toContain('Configure connection')
    })
  })

  // ============================================
  // INPUT HANDLING TESTS
  // ============================================

  describe('Input Handling', () => {
    it('updates query value on input', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('SELECT * FROM users')

      expect(textarea.element.value).toBe('SELECT * FROM users')
    })

    it('disables textarea when disabled prop is true', () => {
      wrapper = createWrapper({ disabled: true })
      expect(wrapper.find('textarea').attributes('disabled')).toBeDefined()
    })

    it('has correct aria-label for accessibility', () => {
      const textarea = wrapper.find('textarea')
      expect(textarea.attributes('aria-label')).toBe('Enter your natural language query')
    })
  })

  // ============================================
  // SUBMIT FUNCTIONALITY TESTS
  // ============================================

  describe('Submit Functionality', () => {
    it('emits submit event with trimmed query on button click', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('  Show me all users  ')

      await wrapper.find('.send-btn').trigger('click')

      expect(wrapper.emitted('submit')).toBeTruthy()
      expect(wrapper.emitted('submit')[0]).toEqual(['Show me all users'])
    })

    it('clears input after submit', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('Test query')

      await wrapper.find('.send-btn').trigger('click')

      expect(textarea.element.value).toBe('')
    })

    it('does not submit empty query', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('   ')

      await wrapper.find('.send-btn').trigger('click')

      expect(wrapper.emitted('submit')).toBeFalsy()
    })

    it('does not submit when disabled', async () => {
      wrapper = createWrapper({ disabled: true })
      const textarea = wrapper.find('textarea')
      await textarea.setValue('Test query')

      // Send button should be disabled
      expect(wrapper.find('.send-btn').attributes('disabled')).toBeDefined()
    })

    it('does not submit when generating', async () => {
      wrapper = createWrapper({ isGenerating: true })

      // Send button should not exist during generation
      expect(wrapper.find('.send-btn').exists()).toBe(false)
    })

    it('disables send button when query is empty', async () => {
      const sendBtn = wrapper.find('.send-btn')
      expect(sendBtn.attributes('disabled')).toBeDefined()
    })

    it('enables send button when query has content', async () => {
      await wrapper.find('textarea').setValue('Test query')
      await nextTick()

      const sendBtn = wrapper.find('.send-btn')
      expect(sendBtn.attributes('disabled')).toBeUndefined()
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
      expect(wrapper.emitted('submit')[0]).toEqual(['Test query'])
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

    it('does not submit on plain Enter', async () => {
      const textarea = wrapper.find('textarea')
      await textarea.setValue('Test query')

      await textarea.trigger('keydown', {
        key: 'Enter'
      })

      expect(wrapper.emitted('submit')).toBeFalsy()
    })

    it('does not submit on Ctrl+Enter when disabled', async () => {
      wrapper = createWrapper({ disabled: true })
      const textarea = wrapper.find('textarea')
      await textarea.setValue('Test query')

      await textarea.trigger('keydown', {
        key: 'Enter',
        ctrlKey: true
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

      await wrapper.find('.stop-btn').trigger('click')

      expect(wrapper.emitted('stop')).toBeTruthy()
    })

    it('stop button has correct title', () => {
      wrapper = createWrapper({ isGenerating: true })
      expect(wrapper.find('.stop-btn').attributes('title')).toBe('Stop generation')
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

    it('setQuery updates the input value', async () => {
      wrapper.vm.setQuery('Prefilled query')
      await nextTick()

      expect(wrapper.find('textarea').element.value).toBe('Prefilled query')
    })
  })

  // ============================================
  // CUSTOM PLACEHOLDER TESTS
  // ============================================

  describe('Custom Placeholder', () => {
    it('uses custom placeholder when provided', () => {
      wrapper = createWrapper({ placeholder: 'Custom placeholder text' })
      expect(wrapper.find('textarea').attributes('placeholder')).toBe('Custom placeholder text')
    })

    it('uses default placeholder when not provided', () => {
      wrapper = mount(QueryInput, {
        global: { stubs: { InputOptions: true } }
      })
      expect(wrapper.find('textarea').attributes('placeholder')).toBe('Ask about your data...')
    })
  })
})
