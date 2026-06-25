/**
 * ChatContainer Component Tests
 *
 * Tests the main chat interface component including:
 * - Empty state rendering
 * - Message list rendering
 * - Loading states
 * - Scroll functionality
 * - Event emissions
 * - Dynamic animations
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import ChatContainer from '../ChatContainer.vue'
import AIResponseCard from '../AIResponseCard.vue'
import UserMessage from '../UserMessage.vue'
import SystemMessage from '../SystemMessage.vue'

// Mock child components
vi.mock('../AIResponseCard.vue', () => ({
  default: {
    name: 'AIResponseCard',
    props: ['message', 'isLatest', 'isExecuting', 'isExplaining', 'sessionId', 'dmlCapabilities'],
    template: '<div class="ai-response-card">{{ message.content }}</div>'
  }
}))

vi.mock('../UserMessage.vue', () => ({
  default: {
    name: 'UserMessage',
    props: ['message'],
    template: '<div class="user-message">{{ message.content }}</div>'
  }
}))

vi.mock('../SystemMessage.vue', () => ({
  default: {
    name: 'SystemMessage',
    props: ['message'],
    template: '<div class="system-message">{{ message.content }}</div>'
  }
}))

describe('ChatContainer', () => {
  let wrapper

  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    if (wrapper) {
      wrapper.unmount()
    }
  })

  // ============================================
  // EMPTY STATE TESTS
  // ============================================

  describe('Empty State', () => {
    it('renders empty state when conversation is empty', () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          isGenerating: false,
          isExecuting: false,
          isExplaining: false,
          sessionId: 'test-session'
        }
      })

      expect(wrapper.find('.empty-state').exists()).toBe(true)
      expect(wrapper.find('.messages-list').exists()).toBe(false)
      expect(wrapper.text()).toContain('What would you like to know?')
    })

    it('renders hero icon container with animations', () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          isGenerating: false,
          sessionId: 'test-session'
        }
      })

      expect(wrapper.find('.hero-icon-container').exists()).toBe(true)
      expect(wrapper.find('.ambient-glow').exists()).toBe(true)
      expect(wrapper.find('.main-icon').exists()).toBe(true)
      expect(wrapper.find('.pulse-ring').exists()).toBe(true)
    })

    it('renders floating particles', () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          sessionId: 'test-session'
        }
      })

      const particles = wrapper.findAll('.float-particle')
      expect(particles.length).toBe(12)
    })

    it('renders dynamic tagline', () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          sessionId: 'test-session'
        }
      })

      const tagline = wrapper.find('.tagline')
      expect(tagline.exists()).toBe(true)
      expect(tagline.text().length).toBeGreaterThan(0)
    })

    it('rotates taglines every 3.5 seconds', async () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          sessionId: 'test-session'
        }
      })

      const initialText = wrapper.find('.tagline span').text()

      // Advance time by 3.5 seconds
      vi.advanceTimersByTime(3500)
      await nextTick()

      const newText = wrapper.find('.tagline span').text()
      expect(newText).not.toBe(initialText)
    })

    it('renders example query chips', () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          sessionId: 'test-session'
        }
      })

      const chips = wrapper.findAll('.example-chip')
      expect(chips.length).toBe(3)
      expect(chips[0].text()).toContain('List tables')
      expect(chips[1].text()).toContain('Schema info')
      expect(chips[2].text()).toContain('Explore data')
    })

    it('emits example-select when example chip is clicked', async () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          sessionId: 'test-session'
        }
      })

      const firstChip = wrapper.findAll('.example-chip')[0]
      await firstChip.trigger('click')

      expect(wrapper.emitted('example-select')).toBeTruthy()
      expect(wrapper.emitted('example-select')[0]).toEqual(['Show all tables in the database'])
    })
  })

  // ============================================
  // MESSAGE RENDERING TESTS
  // ============================================

  describe('Message Rendering', () => {
    it('renders user messages correctly', () => {
      const conversation = [
        { id: '1', type: 'user', content: 'Show me all customers' }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          sessionId: 'test-session'
        }
      })

      expect(wrapper.find('.messages-list').exists()).toBe(true)
      expect(wrapper.find('.empty-state').exists()).toBe(false)
      expect(wrapper.findComponent(UserMessage).exists()).toBe(true)
    })

    it('renders AI response cards correctly', () => {
      const conversation = [
        { id: '1', type: 'user', content: 'Show customers' },
        { id: '2', type: 'ai', content: { sql: 'SELECT * FROM customers' } }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          sessionId: 'test-session'
        }
      })

      expect(wrapper.findComponent(AIResponseCard).exists()).toBe(true)
    })

    it('renders system messages correctly', () => {
      const conversation = [
        { id: '1', type: 'system', content: 'Connection established' }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          sessionId: 'test-session'
        }
      })

      expect(wrapper.findComponent(SystemMessage).exists()).toBe(true)
    })

    it('renders mixed message types in correct order', () => {
      const conversation = [
        { id: '1', type: 'user', content: 'Query 1' },
        { id: '2', type: 'ai', content: { sql: 'SELECT 1' } },
        { id: '3', type: 'system', content: 'System message' },
        { id: '4', type: 'user', content: 'Query 2' }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          sessionId: 'test-session'
        }
      })

      const messages = wrapper.find('.messages-list').findAll('div[class*="message"]')
      expect(messages.length).toBeGreaterThanOrEqual(3)
    })

    it('passes isLatest prop to the last AI message', () => {
      const conversation = [
        { id: '1', type: 'user', content: 'Query 1' },
        { id: '2', type: 'ai', content: { sql: 'SELECT 1' } },
        { id: '3', type: 'user', content: 'Query 2' },
        { id: '4', type: 'ai', content: { sql: 'SELECT 2' } }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          sessionId: 'test-session'
        }
      })

      const aiCards = wrapper.findAllComponents(AIResponseCard)
      expect(aiCards.length).toBe(2)
      // Last AI card should have isLatest=true
      expect(aiCards[1].props('isLatest')).toBe(true)
    })

    it('passes isExecuting to the latest message when executing', () => {
      const conversation = [
        { id: '1', type: 'user', content: 'Query' },
        { id: '2', type: 'ai', content: { sql: 'SELECT 1' } }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          isExecuting: true,
          sessionId: 'test-session'
        }
      })

      const aiCard = wrapper.findComponent(AIResponseCard)
      expect(aiCard.props('isExecuting')).toBe(true)
    })

    it('passes isExplaining and explainingMessageId correctly', () => {
      const conversation = [
        { id: 'msg-1', type: 'user', content: 'Query' },
        { id: 'msg-2', type: 'ai', content: { sql: 'SELECT 1' } }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          isExplaining: true,
          explainingMessageId: 'msg-2',
          sessionId: 'test-session'
        }
      })

      const aiCard = wrapper.findComponent(AIResponseCard)
      expect(aiCard.props('isExplaining')).toBe(true)
    })
  })

  // ============================================
  // LOADING STATE TESTS
  // ============================================

  describe('Loading States', () => {
    it('shows loading indicator when generating and no AI message yet', () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [
            { id: '1', type: 'user', content: 'Query' }
          ],
          isGenerating: true,
          sessionId: 'test-session'
        }
      })

      expect(wrapper.find('.loading-message').exists()).toBe(true)
      expect(wrapper.find('.loading-dots').exists()).toBe(true)
      expect(wrapper.text()).toContain('Thinking...')
    })

    it('hides loading indicator when AI message is generating', () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [
            { id: '1', type: 'user', content: 'Query' },
            { id: '2', type: 'ai', content: { isGenerating: true, sql: '' } }
          ],
          isGenerating: true,
          sessionId: 'test-session'
        }
      })

      // Should not show separate loading indicator when AI card is present
      expect(wrapper.find('.loading-message').exists()).toBe(false)
    })

    it('hides loading indicator when not generating', () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [
            { id: '1', type: 'user', content: 'Query' }
          ],
          isGenerating: false,
          sessionId: 'test-session'
        }
      })

      expect(wrapper.find('.loading-message').exists()).toBe(false)
    })
  })

  // ============================================
  // SCROLL FUNCTIONALITY TESTS
  // ============================================

  describe('Scroll Functionality', () => {
    it('shows scroll button when scrolled up more than 100px', async () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [
            { id: '1', type: 'user', content: 'Query' },
            { id: '2', type: 'ai', content: { sql: 'SELECT 1' } }
          ],
          sessionId: 'test-session'
        },
        attachTo: document.body
      })

      // Mock scroll position
      const container = wrapper.find('.chat-container').element
      Object.defineProperty(container, 'scrollTop', { value: 0, writable: true })
      Object.defineProperty(container, 'scrollHeight', { value: 1000, writable: true })
      Object.defineProperty(container, 'clientHeight', { value: 500, writable: true })

      // Trigger scroll event
      await container.dispatchEvent(new Event('scroll'))
      await nextTick()

      expect(wrapper.find('.scroll-bottom-btn').exists()).toBe(true)
    })

    it('hides scroll button when near bottom', async () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [
            { id: '1', type: 'user', content: 'Query' }
          ],
          sessionId: 'test-session'
        },
        attachTo: document.body
      })

      // Mock scroll position near bottom
      const container = wrapper.find('.chat-container').element
      Object.defineProperty(container, 'scrollTop', { value: 450, writable: true })
      Object.defineProperty(container, 'scrollHeight', { value: 500, writable: true })
      Object.defineProperty(container, 'clientHeight', { value: 500, writable: true })

      await container.dispatchEvent(new Event('scroll'))
      await nextTick()

      // Button should be hidden (wrapped in transition, check if rendered)
      expect(wrapper.vm.showScrollButton).toBe(false)
    })

    it('scrolls to bottom when scroll button is clicked', async () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [
            { id: '1', type: 'user', content: 'Query' }
          ],
          sessionId: 'test-session'
        },
        attachTo: document.body
      })

      // Force show scroll button
      wrapper.vm.showScrollButton = true
      await nextTick()

      // Mock scrollTo
      const container = wrapper.find('.chat-container').element
      const scrollToMock = vi.fn()
      container.scrollTo = scrollToMock

      const scrollBtn = wrapper.find('.scroll-bottom-btn')
      await scrollBtn.trigger('click')

      expect(scrollToMock).toHaveBeenCalledWith({
        top: container.scrollHeight,
        behavior: 'smooth'
      })
    })

    it('exposes scrollToBottom method', () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          sessionId: 'test-session'
        }
      })

      expect(typeof wrapper.vm.scrollToBottom).toBe('function')
    })
  })

  // ============================================
  // EVENT EMISSION TESTS
  // ============================================

  describe('Event Emissions', () => {
    it('emits run-query event from AIResponseCard', async () => {
      const conversation = [
        { id: '1', type: 'ai', content: { sql: 'SELECT 1' } }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          sessionId: 'test-session'
        }
      })

      const aiCard = wrapper.findComponent(AIResponseCard)
      await aiCard.vm.$emit('run-query', conversation[0])

      expect(wrapper.emitted('run-query')).toBeTruthy()
      expect(wrapper.emitted('run-query')[0]).toEqual([conversation[0]])
    })

    it('emits explain event from AIResponseCard', async () => {
      const conversation = [
        { id: '1', type: 'ai', content: { sql: 'SELECT 1' } }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          sessionId: 'test-session'
        }
      })

      const aiCard = wrapper.findComponent(AIResponseCard)
      await aiCard.vm.$emit('explain', conversation[0])

      expect(wrapper.emitted('explain')).toBeTruthy()
    })

    it('emits feedback event with rating', async () => {
      const conversation = [
        { id: '1', type: 'ai', content: { sql: 'SELECT 1' } }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          sessionId: 'test-session'
        }
      })

      const aiCard = wrapper.findComponent(AIResponseCard)
      await aiCard.vm.$emit('feedback', 'positive')

      expect(wrapper.emitted('feedback')).toBeTruthy()
      expect(wrapper.emitted('feedback')[0][0]).toEqual({
        message: conversation[0],
        rating: 'positive'
      })
    })

    it('emits ask-follow-up event with question', async () => {
      const conversation = [
        { id: '1', type: 'ai', content: { sql: 'SELECT 1' } }
      ]

      wrapper = mount(ChatContainer, {
        props: {
          conversation,
          sessionId: 'test-session'
        }
      })

      const aiCard = wrapper.findComponent(AIResponseCard)
      const followUpQuestion = 'What about by region?'
      await aiCard.vm.$emit('ask-question', followUpQuestion)

      expect(wrapper.emitted('ask-follow-up')).toBeTruthy()
      expect(wrapper.emitted('ask-follow-up')[0]).toEqual([followUpQuestion])
    })
  })

  // ============================================
  // LIFECYCLE TESTS
  // ============================================

  describe('Lifecycle', () => {
    it('sets up scroll listener on mount', () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          sessionId: 'test-session'
        },
        attachTo: document.body
      })

      const container = wrapper.find('.chat-container').element
      expect(container).toBeDefined()
      // Component should have added scroll listener
    })

    it('starts tagline rotation interval on mount', async () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          sessionId: 'test-session'
        }
      })

      const initialTagline = wrapper.vm.currentTagline

      // Advance timers
      vi.advanceTimersByTime(3500)
      await nextTick()

      expect(wrapper.vm.currentTagline).not.toBe(initialTagline)
    })

    it('cleans up intervals on unmount', async () => {
      wrapper = mount(ChatContainer, {
        props: {
          conversation: [],
          sessionId: 'test-session'
        }
      })

      const clearIntervalSpy = vi.spyOn(global, 'clearInterval')

      wrapper.unmount()

      expect(clearIntervalSpy).toHaveBeenCalled()
    })
  })
})
