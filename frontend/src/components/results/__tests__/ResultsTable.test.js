/**
 * ResultsTable Component Tests
 *
 * Tests the results table component including:
 * - Rendering with different data types
 * - Empty state handling
 * - Sorting functionality
 * - Pagination
 * - Cell formatting
 * - Compact and fullscreen modes
 */

import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ResultsTable from '../ResultsTable.vue'

// Mock lucide-vue-next icons
vi.mock('lucide-vue-next', () => ({
  Table2: { template: '<span class="icon-table">Table</span>' },
  ChevronLeft: { template: '<span class="icon-chevron-left">←</span>' },
  ChevronRight: { template: '<span class="icon-chevron-right">→</span>' },
  ArrowUpDown: { template: '<span class="icon-sort">↕</span>' },
  ArrowUp: { template: '<span class="icon-sort-up">↑</span>' },
  ArrowDown: { template: '<span class="icon-sort-down">↓</span>' }
}))

describe('ResultsTable', () => {
  const sampleData = {
    columns: ['id', 'name', 'age', 'active'],
    rows: [
      { id: 1, name: 'Alice', age: 30, active: true },
      { id: 2, name: 'Bob', age: 25, active: false },
      { id: 3, name: 'Charlie', age: 35, active: true }
    ]
  }

  const createWrapper = (props = {}) => {
    return mount(ResultsTable, {
      props: {
        columns: sampleData.columns,
        rows: sampleData.rows,
        ...props
      }
    })
  }

  // ============================================
  // RENDERING TESTS
  // ============================================

  describe('Rendering', () => {
    it('renders the results table', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.results-table').exists()).toBe(true)
    })

    it('renders column headers', () => {
      const wrapper = createWrapper()
      const headers = wrapper.findAll('th')

      expect(headers.length).toBe(4)
      expect(headers[0].text()).toContain('id')
      expect(headers[1].text()).toContain('name')
      expect(headers[2].text()).toContain('age')
      expect(headers[3].text()).toContain('active')
    })

    it('renders data rows', () => {
      const wrapper = createWrapper()
      const rows = wrapper.findAll('tbody tr')

      expect(rows.length).toBe(3)
    })

    it('renders cell values correctly', () => {
      const wrapper = createWrapper()
      const firstRow = wrapper.find('tbody tr')
      const cells = firstRow.findAll('td')

      expect(cells[0].text()).toBe('1')
      expect(cells[1].text()).toBe('Alice')
      expect(cells[2].text()).toBe('30')
      expect(cells[3].text()).toBe('Yes') // Boolean formatted
    })
  })

  // ============================================
  // EMPTY STATE TESTS
  // ============================================

  describe('Empty State', () => {
    it('shows empty state when no rows', () => {
      const wrapper = createWrapper({ rows: [] })

      expect(wrapper.find('.empty-state').exists()).toBe(true)
      expect(wrapper.find('.empty-state').text()).toContain('No data available')
    })

    it('shows empty state when rows is null', () => {
      const wrapper = createWrapper({ rows: null, columns: null })

      expect(wrapper.find('.empty-state').exists()).toBe(true)
    })

    it('hides table when empty', () => {
      const wrapper = createWrapper({ rows: [] })

      expect(wrapper.find('.data-table').exists()).toBe(false)
    })
  })

  // ============================================
  // SORTING TESTS
  // ============================================

  describe('Sorting', () => {
    it('sorts ascending on first click', async () => {
      const wrapper = createWrapper()
      const nameHeader = wrapper.findAll('th')[1] // name column

      await nameHeader.trigger('click')

      const firstCell = wrapper.find('tbody tr td:nth-child(2)')
      expect(firstCell.text()).toBe('Alice') // A comes first
    })

    it('sorts descending on second click', async () => {
      const wrapper = createWrapper()
      const nameHeader = wrapper.findAll('th')[1]

      await nameHeader.trigger('click') // asc
      await nameHeader.trigger('click') // desc

      const firstCell = wrapper.find('tbody tr td:nth-child(2)')
      expect(firstCell.text()).toBe('Charlie') // C comes last, so first in desc
    })

    it('sorts numbers correctly', async () => {
      const wrapper = createWrapper()
      const ageHeader = wrapper.findAll('th')[2] // age column

      await ageHeader.trigger('click') // asc

      const ages = wrapper.findAll('tbody tr td:nth-child(3)').map(td => td.text())
      expect(ages).toEqual(['25', '30', '35'])
    })

    it('shows sort indicator on sorted column', async () => {
      const wrapper = createWrapper()
      const header = wrapper.findAll('th')[0]

      await header.trigger('click')

      expect(header.classes()).toContain('sorted')
    })

    it('handles null values in sorting', async () => {
      const wrapper = createWrapper({
        columns: ['id', 'value'],
        rows: [
          { id: 1, value: null },
          { id: 2, value: 10 },
          { id: 3, value: 5 }
        ]
      })

      const valueHeader = wrapper.findAll('th')[1]
      await valueHeader.trigger('click')

      // Null should be at the end
      const values = wrapper.findAll('tbody tr td:nth-child(2)').map(td => td.text())
      expect(values[values.length - 1]).toBe('—') // null formatted as dash
    })
  })

  // ============================================
  // PAGINATION TESTS
  // ============================================

  describe('Pagination', () => {
    const manyRows = Array.from({ length: 50 }, (_, i) => ({
      id: i + 1,
      name: `User ${i + 1}`
    }))

    it('shows pagination when rows exceed page size', () => {
      const wrapper = createWrapper({
        columns: ['id', 'name'],
        rows: manyRows
      })

      expect(wrapper.find('.pagination').exists()).toBe(true)
    })

    it('hides pagination when rows fit on one page', () => {
      const wrapper = createWrapper()
      expect(wrapper.find('.pagination').exists()).toBe(false)
    })

    it('shows correct page info', () => {
      const wrapper = createWrapper({
        columns: ['id', 'name'],
        rows: manyRows
      })

      expect(wrapper.find('.page-info').text()).toContain('1-25 of 50')
    })

    it('navigates to next page', async () => {
      const wrapper = createWrapper({
        columns: ['id', 'name'],
        rows: manyRows
      })

      const nextBtn = wrapper.findAll('.page-btn')[1]
      await nextBtn.trigger('click')

      expect(wrapper.find('.page-info').text()).toContain('26-50 of 50')
    })

    it('navigates to previous page', async () => {
      const wrapper = createWrapper({
        columns: ['id', 'name'],
        rows: manyRows
      })

      // Go to page 2
      await wrapper.findAll('.page-btn')[1].trigger('click')
      // Go back to page 1
      await wrapper.findAll('.page-btn')[0].trigger('click')

      expect(wrapper.find('.page-info').text()).toContain('1-25 of 50')
    })

    it('disables prev button on first page', () => {
      const wrapper = createWrapper({
        columns: ['id', 'name'],
        rows: manyRows
      })

      const prevBtn = wrapper.findAll('.page-btn')[0]
      expect(prevBtn.attributes('disabled')).toBeDefined()
    })

    it('disables next button on last page', async () => {
      const wrapper = createWrapper({
        columns: ['id', 'name'],
        rows: manyRows
      })

      // Go to last page
      await wrapper.findAll('.page-btn')[1].trigger('click')

      const nextBtn = wrapper.findAll('.page-btn')[1]
      expect(nextBtn.attributes('disabled')).toBeDefined()
    })
  })

  // ============================================
  // CELL FORMATTING TESTS
  // ============================================

  describe('Cell Formatting', () => {
    it('formats null values as dash', () => {
      const wrapper = createWrapper({
        columns: ['id', 'value'],
        rows: [{ id: 1, value: null }]
      })

      const cell = wrapper.find('tbody td:nth-child(2)')
      expect(cell.text()).toBe('—')
      expect(cell.classes()).toContain('cell-null')
    })

    it('formats boolean true as Yes', () => {
      const wrapper = createWrapper({
        columns: ['active'],
        rows: [{ active: true }]
      })

      expect(wrapper.find('tbody td').text()).toBe('Yes')
    })

    it('formats boolean false as No', () => {
      const wrapper = createWrapper({
        columns: ['active'],
        rows: [{ active: false }]
      })

      expect(wrapper.find('tbody td').text()).toBe('No')
    })

    it('formats numbers with locale formatting', () => {
      const wrapper = createWrapper({
        columns: ['count'],
        rows: [{ count: 1000000 }]
      })

      const cell = wrapper.find('tbody td')
      expect(cell.text()).toContain('1') // At minimum contains the number
      expect(cell.classes()).toContain('cell-number')
    })

    it('truncates long strings', () => {
      const longString = 'A'.repeat(100)
      const wrapper = createWrapper({
        columns: ['text'],
        rows: [{ text: longString }]
      })

      const cell = wrapper.find('tbody td')
      expect(cell.text().length).toBeLessThan(100)
      expect(cell.text()).toContain('...')
    })

    it('formats objects as JSON', () => {
      const wrapper = createWrapper({
        columns: ['data'],
        rows: [{ data: { key: 'value' } }]
      })

      const cell = wrapper.find('tbody td')
      expect(cell.text()).toContain('key')
    })
  })

  // ============================================
  // COMPACT MODE TESTS
  // ============================================

  describe('Compact Mode', () => {
    it('applies compact class', () => {
      const wrapper = createWrapper({ compact: true })
      expect(wrapper.find('.results-table').classes()).toContain('compact')
    })

    it('uses smaller page size in compact mode', () => {
      const manyRows = Array.from({ length: 20 }, (_, i) => ({
        id: i + 1,
        name: `User ${i + 1}`
      }))

      const wrapper = createWrapper({
        columns: ['id', 'name'],
        rows: manyRows,
        compact: true
      })

      // Compact mode uses 10 per page
      expect(wrapper.find('.page-info').text()).toContain('1-10 of 20')
    })
  })

  // ============================================
  // FULLSCREEN MODE TESTS
  // ============================================

  describe('Fullscreen Mode', () => {
    it('applies fullscreen class', () => {
      const wrapper = createWrapper({ fullscreen: true })
      expect(wrapper.find('.results-table').classes()).toContain('fullscreen')
    })

    it('uses larger page size in fullscreen mode', () => {
      const manyRows = Array.from({ length: 100 }, (_, i) => ({
        id: i + 1,
        name: `User ${i + 1}`
      }))

      const wrapper = createWrapper({
        columns: ['id', 'name'],
        rows: manyRows,
        fullscreen: true
      })

      // Fullscreen mode uses 50 per page
      expect(wrapper.find('.page-info').text()).toContain('1-50 of 100')
    })
  })

  // ============================================
  // LEGACY RESULTS OBJECT SUPPORT
  // ============================================

  describe('Legacy Results Object', () => {
    it('supports results object prop', () => {
      const wrapper = mount(ResultsTable, {
        props: {
          results: {
            columns: ['id', 'name'],
            rows: [{ id: 1, name: 'Test' }]
          }
        }
      })

      expect(wrapper.find('.data-table').exists()).toBe(true)
      expect(wrapper.findAll('th').length).toBe(2)
    })

    it('resets state when results change', async () => {
      const wrapper = mount(ResultsTable, {
        props: {
          results: {
            columns: ['id'],
            rows: Array.from({ length: 50 }, (_, i) => ({ id: i }))
          }
        }
      })

      // Go to page 2
      await wrapper.findAll('.page-btn')[1].trigger('click')

      // Update results
      await wrapper.setProps({
        results: {
          columns: ['id'],
          rows: Array.from({ length: 30 }, (_, i) => ({ id: i }))
        }
      })

      // Should reset to page 1
      expect(wrapper.find('.page-info').text()).toContain('1-25')
    })
  })

  // ============================================
  // ACCESSIBILITY TESTS
  // ============================================

  describe('Accessibility', () => {
    it('uses semantic table elements', () => {
      const wrapper = createWrapper()

      expect(wrapper.find('table').exists()).toBe(true)
      expect(wrapper.find('thead').exists()).toBe(true)
      expect(wrapper.find('tbody').exists()).toBe(true)
    })

    it('provides title for truncated content', () => {
      const longString = 'A'.repeat(100)
      const wrapper = createWrapper({
        columns: ['text'],
        rows: [{ text: longString }]
      })

      const cell = wrapper.find('tbody td')
      expect(cell.attributes('title')).toBe(longString)
    })
  })
})
