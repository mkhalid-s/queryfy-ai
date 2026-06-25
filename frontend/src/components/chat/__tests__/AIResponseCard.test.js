/**
 * AIResponseCard Component Tests
 *
 * Tests the AI response card including:
 * - Header rendering
 * - Thinking/loading states
 * - Analyst mode features
 * - Action buttons
 * - Feedback mechanism
 * - Event emissions
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import AIResponseCard from '../AIResponseCard.vue'

// Mock child components
vi.mock('../AgentTimeline.vue', () => ({
  default: {
    name: 'AgentTimeline',
    props: ['steps', 'defaultExpanded'],
    template: '<div class="agent-timeline">Timeline</div>'
  }
}))

vi.mock('../ContentTabs.vue', () => ({
  default: {
    name: 'ContentTabs',
    props: ['sql', 'results', 'chartSpec', 'sessionId', 'dmlCapabilities'],
    template: '<div class="content-tabs">Tabs</div>'
  }
}))

vi.mock('../../results/ResultsTable.vue', () => ({
  default: {
    name: 'ResultsTable',
    props: ['columns', 'rows', 'rowCount', 'fullscreen'],
    template: '<div class="results-table">Table</div>'
  }
}))

vi.mock('./analyst/InsightCard.vue', () => ({
  default: {
    name: 'InsightCard',
    props: ['insight'],
    template: '<div class="insight-card">{{ insight.message }}</div>'
  }
}))

vi.mock('./analyst/FollowUpSuggestions.vue', () => ({
  default: {
    name: 'FollowUpSuggestions',
    props: ['suggestions'],
    template: '<div class="follow-up-suggestions" @click="$emit(\'ask-question\', \'test question\')">Suggestions</div>'
  }
}))

vi.mock('./analyst/DataQualityIndicator.vue', () => ({
  default: {
    name: 'DataQualityIndicator',
    props: ['quality'],
    template: '<div class="data-quality-indicator">Quality: {{ quality.overall_score }}</div>'
  }
}))

describe('AIResponseCard', () => {
  let wrapper

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
  })

  // ============================================
  // HEADER TESTS
  // ============================================

  describe('Header', () => {
    it('renders standard mode header with Bot icon', () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1', mode: 'standard' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.find('.card-header').exists()).toBe(true)
      expect(wrapper.find('.ai-avatar').exists()).toBe(true)
      expect(wrapper.text()).toContain('QueryfyAI')
    })

    it('renders analyst mode header with Sparkles icon', () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1', mode: 'analyst' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.text()).toContain('Analyst')
    })

    it('shows follow-up indicator when isFollowUp is true', () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1', isFollowUp: true },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.find('.follow-up-dot').exists()).toBe(true)
    })

    it('formats timestamp correctly', () => {
      const timestamp = new Date('2024-01-15T10:30:00Z')
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: timestamp.toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const timeText = wrapper.find('.message-time').text()
      expect(timeText.length).toBeGreaterThan(0)
    })
  })

  // ============================================
  // LOADING STATE TESTS
  // ============================================

  describe('Loading States', () => {
    it('shows thinking state when isGenerating is true', () => {
      const message = {
        id: '1',
        content: { isGenerating: true },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.find('.thinking-state').exists()).toBe(true)
      expect(wrapper.find('.thinking-indicator').exists()).toBe(true)
      expect(wrapper.findAll('.thinking-dot').length).toBe(3)
    })

    it('shows default thinking text', () => {
      const message = {
        id: '1',
        content: { isGenerating: true },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.find('.thinking-text').text()).toContain('Thinking...')
    })

    it('hides thinking state when isGenerating is false', () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1', isGenerating: false },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.find('.thinking-state').exists()).toBe(false)
    })
  })

  // ============================================
  // ANALYST MODE TESTS
  // ============================================

  describe('Analyst Mode', () => {
    it('renders answer section in analyst mode', () => {
      const message = {
        id: '1',
        content: {
          mode: 'analyst',
          answer: 'Your top customer is ACME Corp with $1.2M in revenue.',
          sql: 'SELECT * FROM customers'
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.find('.answer-section').exists()).toBe(true)
      expect(wrapper.find('.answer-text').exists()).toBe(true)
    })

    it('renders key findings when present', () => {
      const message = {
        id: '1',
        content: {
          mode: 'analyst',
          answer: 'Analysis complete',
          keyFindings: [
            'Total revenue: $5M',
            'Top customer accounts for 25%',
            'Growth rate: 15% MoM'
          ],
          sql: 'SELECT * FROM revenue'
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const findings = wrapper.findAll('.finding-item')
      expect(findings.length).toBe(3)
      expect(wrapper.text()).toContain('Total revenue: $5M')
    })

    it('renders data quality indicator when present', () => {
      const message = {
        id: '1',
        content: {
          mode: 'analyst',
          answer: 'Analysis',
          dataQuality: {
            overall_score: 85,
            completeness: 90,
            issues: []
          },
          sql: 'SELECT 1'
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.findComponent({ name: 'DataQualityIndicator' }).exists()).toBe(true)
    })

    it('renders insights when present', () => {
      const message = {
        id: '1',
        content: {
          mode: 'analyst',
          answer: 'Analysis',
          insights: [
            { type: 'trend', severity: 'info', message: 'Revenue increasing' },
            { type: 'anomaly', severity: 'warning', message: 'Spike detected' }
          ],
          sql: 'SELECT 1'
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.find('.insights-section').exists()).toBe(true)
      expect(wrapper.findAllComponents({ name: 'InsightCard' }).length).toBe(2)
    })
  })

  // ============================================
  // CONTENT TABS TESTS
  // ============================================

  describe('Content Tabs', () => {
    it('renders ContentTabs when SQL is present', () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT * FROM customers' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.findComponent({ name: 'ContentTabs' }).exists()).toBe(true)
    })

    it('passes SQL and results to ContentTabs', () => {
      const message = {
        id: '1',
        content: {
          sql: 'SELECT * FROM customers',
          rawResult: {
            columns: ['id', 'name'],
            rows: [[1, 'Alice'], [2, 'Bob']],
            row_count: 2
          }
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const tabs = wrapper.findComponent({ name: 'ContentTabs' })
      expect(tabs.props('sql')).toBe('SELECT * FROM customers')
      expect(tabs.props('results')).toEqual(message.content.rawResult)
    })

    it('passes chart spec to ContentTabs', () => {
      const chartSpec = {
        chart_type: 'bar',
        title: 'Revenue by Region',
        x_axis: 'region',
        y_axis: 'revenue'
      }

      const message = {
        id: '1',
        content: {
          sql: 'SELECT region, SUM(revenue) FROM orders GROUP BY region',
          chart: chartSpec
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const tabs = wrapper.findComponent({ name: 'ContentTabs' })
      expect(tabs.props('chartSpec')).toEqual(chartSpec)
    })
  })

  // ============================================
  // FOLLOW-UP SUGGESTIONS TESTS
  // ============================================

  describe('Follow-Up Suggestions', () => {
    it('renders follow-up suggestions when present', () => {
      const message = {
        id: '1',
        content: {
          sql: 'SELECT * FROM customers',
          suggestions: [
            { question: 'What about by region?' },
            { question: 'Show me trends over time' }
          ]
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.findComponent({ name: 'FollowUpSuggestions' }).exists()).toBe(true)
    })

    it('emits ask-question when suggestion is clicked', async () => {
      const message = {
        id: '1',
        content: {
          sql: 'SELECT * FROM customers',
          suggestions: [{ question: 'Show me more' }]
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const suggestions = wrapper.findComponent({ name: 'FollowUpSuggestions' })
      await suggestions.vm.$emit('ask-question', 'test question')

      expect(wrapper.emitted('ask-question')).toBeTruthy()
      expect(wrapper.emitted('ask-question')[0]).toEqual(['test question'])
    })
  })

  // ============================================
  // DETAILS SECTION TESTS
  // ============================================

  describe('Details Section', () => {
    it('shows details section when agent steps are present', () => {
      const message = {
        id: '1',
        content: {
          sql: 'SELECT * FROM customers',
          agentSteps: [
            { type: 'tool_call', tool: 'search_tables' },
            { type: 'tool_call', tool: 'execute_sql' }
          ],
          isGenerating: false
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.find('.details-section').exists()).toBe(true)
      expect(wrapper.find('.details-toggle').exists()).toBe(true)
    })

    it('toggles details visibility when clicked', async () => {
      const message = {
        id: '1',
        content: {
          sql: 'SELECT * FROM customers',
          agentSteps: [{ type: 'tool_call', tool: 'search_tables' }],
          isGenerating: false
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.find('.details-content').exists()).toBe(false)

      const toggle = wrapper.find('.details-toggle')
      await toggle.trigger('click')
      await nextTick()

      expect(wrapper.find('.details-content').exists()).toBe(true)
    })

    it('shows correct details label with steps and tools', () => {
      const message = {
        id: '1',
        content: {
          sql: 'SELECT * FROM customers',
          agentSteps: [
            { type: 'tool_call', tool: 'search_tables' },
            { type: 'tool_call', tool: 'execute_sql' }
          ],
          toolsUsed: ['search_tables', 'execute_sql'],
          isGenerating: false
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const label = wrapper.find('.details-toggle').text()
      expect(label).toContain('steps')
      expect(label).toContain('tools')
    })
  })

  // ============================================
  // ACTION BUTTONS TESTS
  // ============================================

  describe('Action Buttons', () => {
    it('renders Run button when SQL is present', () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT * FROM customers' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const runBtn = wrapper.find('.action-btn.primary')
      expect(runBtn.exists()).toBe(true)
      expect(runBtn.text()).toContain('Run')
    })

    it('disables Run button when isValid is false', () => {
      const message = {
        id: '1',
        content: { sql: 'INVALID SQL', isValid: false },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const runBtn = wrapper.find('.action-btn.primary')
      expect(runBtn.attributes('disabled')).toBeDefined()
    })

    it('shows executing state when isExecuting is true', () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, isExecuting: true, sessionId: 'test-session' }
      })

      const runBtn = wrapper.find('.action-btn.primary')
      expect(runBtn.text()).toContain('Running...')
    })

    it('emits run-query when Run button is clicked', async () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const runBtn = wrapper.find('.action-btn.primary')
      await runBtn.trigger('click')

      expect(wrapper.emitted('run-query')).toBeTruthy()
    })

    it('renders Copy button', () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      // Find copy button by checking title attribute
      const buttons = wrapper.findAll('.action-btn.ghost')
      const copyBtn = buttons.find(btn => btn.attributes('title') === 'Copy SQL')
      expect(copyBtn).toBeTruthy()
    })

    it('copies SQL to clipboard when Copy button is clicked', async () => {
      const mockClipboard = {
        writeText: vi.fn().mockResolvedValue(undefined)
      }
      Object.assign(navigator, { clipboard: mockClipboard })

      const message = {
        id: '1',
        content: { sql: 'SELECT * FROM customers' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const buttons = wrapper.findAll('.action-btn.ghost')
      const copyBtn = buttons.find(btn => btn.attributes('title') === 'Copy SQL')
      await copyBtn.trigger('click')

      expect(mockClipboard.writeText).toHaveBeenCalledWith('SELECT * FROM customers')
      expect(wrapper.emitted('copy')).toBeTruthy()
    })

    it('renders Explain button when no explanation exists', () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const buttons = wrapper.findAll('.action-btn.ghost')
      const explainBtn = buttons.find(btn => btn.attributes('title') === 'Explain SQL')
      expect(explainBtn).toBeTruthy()
    })

    it('emits explain event when Explain button is clicked', async () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const buttons = wrapper.findAll('.action-btn.ghost')
      const explainBtn = buttons.find(btn => btn.attributes('title') === 'Explain SQL')
      await explainBtn.trigger('click')

      expect(wrapper.emitted('explain')).toBeTruthy()
    })

    it('emits export event when Export button is clicked', async () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const buttons = wrapper.findAll('.action-btn.ghost')
      const exportBtn = buttons.find(btn => btn.attributes('title') === 'Export results')
      await exportBtn.trigger('click')

      expect(wrapper.emitted('export')).toBeTruthy()
    })
  })

  // ============================================
  // FEEDBACK TESTS
  // ============================================

  describe('Feedback', () => {
    it('renders thumbs up and thumbs down buttons', () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const feedbackBtns = wrapper.findAll('.feedback-btn')
      expect(feedbackBtns.length).toBe(2)
    })

    it('emits positive feedback when thumbs up is clicked', async () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const feedbackBtns = wrapper.findAll('.feedback-btn')
      await feedbackBtns[0].trigger('click')

      expect(wrapper.emitted('feedback')).toBeTruthy()
      expect(wrapper.emitted('feedback')[0]).toEqual([5])
    })

    it('emits negative feedback when thumbs down is clicked', async () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const feedbackBtns = wrapper.findAll('.feedback-btn')
      await feedbackBtns[1].trigger('click')

      expect(wrapper.emitted('feedback')).toBeTruthy()
      expect(wrapper.emitted('feedback')[0]).toEqual([1])
    })

    it('adds active class to selected feedback button', async () => {
      const message = {
        id: '1',
        content: { sql: 'SELECT 1' },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      const feedbackBtns = wrapper.findAll('.feedback-btn')
      await feedbackBtns[0].trigger('click')
      await nextTick()

      expect(feedbackBtns[0].classes()).toContain('active')
    })
  })

  // ============================================
  // FULLSCREEN MODAL TESTS
  // ============================================

  describe('Fullscreen Modal', () => {
    it('does not show modal by default', () => {
      const message = {
        id: '1',
        content: {
          sql: 'SELECT 1',
          rawResult: { columns: ['id'], rows: [[1]], row_count: 1 }
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' }
      })

      expect(wrapper.find('.modal-overlay').exists()).toBe(false)
    })

    it('shows modal when fullscreen is triggered', async () => {
      const message = {
        id: '1',
        content: {
          sql: 'SELECT 1',
          rawResult: { columns: ['id'], rows: [[1]], row_count: 1 }
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' },
        attachTo: document.body
      })

      // Directly set showFullscreen to true (simulating ContentTabs emitting fullscreen)
      wrapper.vm.showFullscreen = true
      await nextTick()

      // Modal is rendered via Teleport to body, so check document.body
      const modalOverlay = document.querySelector('.modal-overlay')
      expect(modalOverlay).toBeTruthy()
    })

    it('closes modal when close button is clicked', async () => {
      const message = {
        id: '1',
        content: {
          sql: 'SELECT 1',
          rawResult: { columns: ['id'], rows: [[1]], row_count: 1 }
        },
        timestamp: new Date().toISOString()
      }

      wrapper = mount(AIResponseCard, {
        props: { message, sessionId: 'test-session' },
        attachTo: document.body
      })

      // Open modal
      wrapper.vm.showFullscreen = true
      await nextTick()

      // Close modal by finding the button in document.body (teleported)
      const closeBtn = document.querySelector('.modal-close')
      expect(closeBtn).toBeTruthy()
      closeBtn.click()
      await nextTick()

      expect(wrapper.vm.showFullscreen).toBe(false)
    })
  })
})
